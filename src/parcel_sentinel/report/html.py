from __future__ import annotations

import json
from datetime import datetime, timezone

from .render import band_to_b64, ndvi_to_b64

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0f1117; color: #e0e0e0; font-size: 14px; }
h1 { font-size: 1.3rem; font-weight: 600; color: #fff; }
h2 { font-size: 1rem; font-weight: 600; color: #9ca3af; text-transform: uppercase;
     letter-spacing: 0.08em; margin-bottom: 12px; }
.header { padding: 20px 24px 16px; border-bottom: 1px solid #1e2130; }
.header small { color: #6b7280; font-size: 0.78rem; font-family: monospace; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px; }
.grid-2 { display: grid; grid-template-columns: auto 1fr; gap: 24px;
          align-items: start; margin-bottom: 28px; }
.card { background: #161b27; border: 1px solid #1e2130; border-radius: 8px;
        padding: 20px; margin-bottom: 24px; }
.thumbnail img { border-radius: 6px; display: block; max-width: 300px; }
.thumbnail .no-thumb { width: 300px; height: 200px; background: #1e2130;
                        border-radius: 6px; display: flex; align-items: center;
                        justify-content: center; color: #4b5563; font-size: 0.8rem; }

/* Scores */
.scores { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.score-item label { display: block; color: #9ca3af; font-size: 0.8rem; margin-bottom: 4px; }
.score-item .value { font-size: 1.6rem; font-weight: 700; color: #fff; margin-bottom: 6px; }
.bar-bg { height: 6px; background: #1e2130; border-radius: 3px; }
.bar-fill { height: 6px; border-radius: 3px; }
.drought  { background: #ef4444; }
.wetness  { background: #3b82f6; }
.heat     { background: #22c55e; }
.composite{ background: #a855f7; }
.composite-big { font-size: 2.2rem; font-weight: 800; color: #a855f7; }

/* Features table */
.feat-table { width: 100%; border-collapse: collapse; }
.feat-table td { padding: 7px 10px; border-bottom: 1px solid #1e2130; }
.feat-table td:first-child { color: #9ca3af; font-family: monospace; font-size: 0.82rem; }
.feat-table td:last-child  { text-align: right; font-weight: 500; }

/* Quality */
.quality-row { display: flex; gap: 24px; flex-wrap: wrap; }
.quality-item { flex: 1; min-width: 120px; }
.quality-item .q-val { font-size: 1.4rem; font-weight: 700; color: #fff; }
.quality-item .q-lbl { font-size: 0.78rem; color: #6b7280; margin-top: 2px; }
.flag { display: inline-block; background: #7c2d12; color: #fca5a5;
        font-size: 0.72rem; border-radius: 4px; padding: 2px 6px; margin-top: 6px; }

/* Scene grid */
.scene-grid { overflow-x: auto; }
table.scenes { border-collapse: collapse; min-width: 100%; }
table.scenes th { padding: 8px 12px; text-align: left; color: #6b7280;
                  font-size: 0.78rem; font-weight: 500; border-bottom: 1px solid #1e2130; }
table.scenes td { padding: 8px 12px; border-bottom: 1px solid #141824;
                  vertical-align: middle; }
table.scenes td:first-child { font-family: monospace; font-size: 0.82rem; color: #9ca3af; }
table.scenes img { display: block; width: 128px; height: 128px;
                   image-rendering: pixelated; border-radius: 4px; }
.no-img { width: 128px; height: 128px; background: #1e2130; border-radius: 4px;
          display: flex; align-items: center; justify-content: center;
          color: #4b5563; font-size: 0.7rem; }

/* Chart */
.chart-wrap { position: relative; height: 260px; }

/* No-data */
.no-data { color: #4b5563; font-style: italic; font-size: 0.85rem; }
"""

_CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"


def _score_bar(label: str, value: int | None, css_class: str) -> str:
    if value is None:
        return f'<div class="score-item"><label>{label}</label><div class="value">—</div></div>'
    pct = max(0, min(100, value))
    return f"""
    <div class="score-item">
      <label>{label}</label>
      <div class="value">{value}</div>
      <div class="bar-bg"><div class="bar-fill {css_class}" style="width:{pct}%"></div></div>
    </div>"""


def _feature_rows(features: dict) -> str:
    if not features:
        return '<tr><td colspan="2" class="no-data">No features computed yet.</td></tr>'
    rows = []
    for k, v in sorted(features.items()):
        if isinstance(v, float):
            display = f"{v:.4f}"
        else:
            display = str(v)
        rows.append(f"<tr><td>{k}</td><td>{display}</td></tr>")
    return "\n".join(rows)


def _chart_datasets(series: dict[str, list[dict]]) -> tuple[list[str], str]:
    """Build Chart.js labels and datasets JSON from timeseries dicts."""
    all_months: list[str] = []
    for records in series.values():
        for r in records:
            m = r.get("month", "")
            if m and m not in all_months:
                all_months.append(m)
    all_months.sort()

    colors = {
        "ndvi": {"border": "#22c55e", "bg": "rgba(34,197,94,0.15)"},
        "ndwi": {"border": "#3b82f6", "bg": "rgba(59,130,246,0.15)"},
    }
    datasets = []
    for metric, records in series.items():
        by_month = {r["month"]: r.get("mean") for r in records}
        data = [by_month.get(m) for m in all_months]
        c = colors.get(metric, {"border": "#a855f7", "bg": "rgba(168,85,247,0.15)"})
        datasets.append({
            "label": metric.upper(),
            "data": data,
            "borderColor": c["border"],
            "backgroundColor": c["bg"],
            "fill": True,
            "tension": 0.3,
            "spanGaps": True,
            "pointRadius": 3,
        })

    labels_json = json.dumps(all_months)
    datasets_json = json.dumps(datasets)
    return all_months, f"labels: {labels_json}, datasets: {datasets_json}"


def _scene_rows(scene_months: list[dict]) -> str:
    if not scene_months:
        return '<tr><td colspan="4" class="no-data">No scene images cached yet.</td></tr>'
    rows = []
    for entry in scene_months:
        month = entry["month_key"]
        bands = entry["bands"]
        nir, red = bands.get("B08"), bands.get("B04")

        def img_or_empty(b64: str | None, alt: str) -> str:
            if b64:
                return f'<img src="data:image/png;base64,{b64}" alt="{alt}">'
            return f'<div class="no-img">no {alt}</div>'

        b04_b64 = band_to_b64(red) if red is not None else None
        b08_b64 = band_to_b64(nir) if nir is not None else None
        ndvi_b64 = ndvi_to_b64(nir, red) if (nir is not None and red is not None) else None

        rows.append(f"""
        <tr>
          <td>{month}</td>
          <td>{img_or_empty(b04_b64, 'B04 Red')}</td>
          <td>{img_or_empty(b08_b64, 'B08 NIR')}</td>
          <td>{img_or_empty(ndvi_b64, 'NDVI')}</td>
        </tr>""")
    return "\n".join(rows)


def build_report_html(
    parcel_key: str,
    geometry_geojson: dict | None,
    scores: dict | None,
    features: dict | None,
    quality: dict | None,
    timeseries: dict[str, list[dict]] | None,
    scene_months: list[dict],
    processing_version: str,
    score_version: str,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    key_short = parcel_key[:24] + "..." if len(parcel_key) > 24 else parcel_key

    # Thumbnail
    thumb_url = f"/v1/thumbnail/{parcel_key}.png"
    if geometry_geojson:
        thumb_html = f'<img src="{thumb_url}" alt="Parcel map" onerror="this.parentNode.innerHTML=\'<div class=&quot;no-thumb&quot;>Thumbnail unavailable</div>\'">'
    else:
        thumb_html = '<div class="no-thumb">No geometry stored</div>'

    # Scores
    s = scores or {}
    composite = s.get("composite_score")
    composite_html = f'<div class="composite-big">{composite}</div>' if composite is not None else '<div class="composite-big">—</div>'
    score_bars = (
        _score_bar("Drought", s.get("drought_score"), "drought") +
        _score_bar("Wetness", s.get("wetness_score"), "wetness") +
        _score_bar("Heat mitigation", s.get("heat_mitigation_score"), "heat")
    )

    # Quality
    q = quality or {}
    months_total = q.get("months_total", "—")
    months_observed = q.get("months_observed", "—")
    cloud_frac = q.get("mean_cloud_fraction")
    cloud_pct = f"{cloud_frac * 100:.1f}%" if cloud_frac is not None else "—"
    flags = q.get("flags", [])
    flag_html = "".join(f'<span class="flag">{f}</span> ' for f in flags) if flags else ""
    coverage_pct = (
        f"{months_observed / months_total * 100:.0f}%"
        if isinstance(months_observed, int) and isinstance(months_total, int) and months_total > 0
        else "—"
    )

    # Feature rows
    feat = features or {}
    feat_rows = _feature_rows(feat)

    # Chart
    if timeseries:
        _, chart_data = _chart_datasets(timeseries)
        chart_html = f"""
        <div class="chart-wrap">
          <canvas id="tsChart"></canvas>
        </div>
        <script>
        new Chart(document.getElementById('tsChart'), {{
          type: 'line',
          data: {{ {chart_data} }},
          options: {{
            responsive: true, maintainAspectRatio: false,
            plugins: {{ legend: {{ labels: {{ color: '#9ca3af' }} }} }},
            scales: {{
              x: {{ ticks: {{ color: '#6b7280', maxTicksLimit: 12 }},
                    grid: {{ color: '#1e2130' }} }},
              y: {{ ticks: {{ color: '#6b7280' }}, grid: {{ color: '#1e2130' }},
                    title: {{ display: true, text: 'Index value', color: '#6b7280' }} }}
            }}
          }}
        }});
        </script>"""
    else:
        chart_html = '<p class="no-data">No time series stored yet. Call /v1/parcel/timeseries first.</p>'

    # Scene image rows
    scene_rows = _scene_rows(scene_months)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Parcel Report &mdash; {key_short}</title>
  <script src="{_CHART_JS_CDN}"></script>
  <style>{_CSS}</style>
</head>
<body>

<div class="header">
  <h1>Parcel Sentinel Report</h1>
  <small>{parcel_key} &nbsp;&bull;&nbsp; generated {generated}</small>
</div>

<div class="container">

  <!-- Overview -->
  <div class="grid-2">
    <div class="card thumbnail">{thumb_html}</div>
    <div class="card">
      <h2>Composite score</h2>
      {composite_html}
      <div style="margin-top:20px">
        <h2>Sub-scores</h2>
        <div class="scores">{score_bars}</div>
      </div>
    </div>
  </div>

  <!-- Quality -->
  <div class="card">
    <h2>Data quality</h2>
    <div class="quality-row">
      <div class="quality-item">
        <div class="q-val">{months_observed} / {months_total}</div>
        <div class="q-lbl">Months observed</div>
      </div>
      <div class="quality-item">
        <div class="q-val">{coverage_pct}</div>
        <div class="q-lbl">Coverage</div>
      </div>
      <div class="quality-item">
        <div class="q-val">{cloud_pct}</div>
        <div class="q-lbl">Mean cloud fraction</div>
      </div>
      <div class="quality-item">
        <div class="q-val" style="font-size:0.9rem">{flag_html or '&mdash;'}</div>
        <div class="q-lbl">Flags</div>
      </div>
    </div>
    <div style="margin-top:12px;color:#4b5563;font-size:0.78rem">
      Processing: {processing_version} &nbsp;&bull;&nbsp; Score: {score_version}
    </div>
  </div>

  <!-- Time series chart -->
  <div class="card">
    <h2>Time series</h2>
    {chart_html}
  </div>

  <!-- Features -->
  <div class="card">
    <h2>Derived features</h2>
    <table class="feat-table">
      <tbody>{feat_rows}</tbody>
    </table>
  </div>

  <!-- Scene images -->
  <div class="card">
    <h2>Scene images (most recent {len(scene_months)})</h2>
    <div class="scene-grid">
      <table class="scenes">
        <thead>
          <tr>
            <th>Month</th>
            <th>B04 &mdash; Red (gray)</th>
            <th>B08 &mdash; NIR (gray)</th>
            <th>NDVI (color)</th>
          </tr>
        </thead>
        <tbody>{scene_rows}</tbody>
      </table>
    </div>
  </div>

</div>
</body>
</html>"""
