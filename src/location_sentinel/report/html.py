from __future__ import annotations

import json
from datetime import datetime, timezone

from .render import band_to_b64, bsi_to_b64, nbr_to_b64, ndmi_to_b64, ndsi_to_b64, ndvi_to_b64, ndwi_to_b64, vv_dn_to_b64
from ..compute.scoring import climate_profile_label, climate_weights_for_code

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f1f5f9; color: #1e293b; font-size: 14px; }
h1 { font-size: 1.3rem; font-weight: 700; color: #0f172a; }
h2 { font-size: 0.72rem; font-weight: 700; color: #94a3b8; text-transform: uppercase;
     letter-spacing: 0.1em; margin-bottom: 14px; }
.header { padding: 20px 24px 16px; border-bottom: 1px solid #e2e8f0; background: #fff; }
.header small { color: #94a3b8; font-size: 0.78rem; font-family: monospace; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px; }
.grid-2 { display: grid; grid-template-columns: auto 1fr; gap: 20px;
          align-items: start; margin-bottom: 24px; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
        padding: 22px; margin-bottom: 20px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
.thumbnail img { border-radius: 6px; display: block; max-width: 300px; }
.thumbnail .no-thumb { width: 300px; height: 200px; background: #f8fafc;
                        border: 1px solid #e2e8f0; border-radius: 6px;
                        display: flex; align-items: center;
                        justify-content: center; color: #94a3b8; font-size: 0.8rem; }

/* Scores */
.scores { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.score-item label { display: block; color: #64748b; font-size: 0.8rem; margin-bottom: 4px; }
.score-item .value { font-size: 1.6rem; font-weight: 700; color: #0f172a; margin-bottom: 6px; }
.bar-bg { height: 6px; background: #e2e8f0; border-radius: 3px; }
.bar-fill { height: 6px; border-radius: 3px; }

/* Features table */
.feat-table { width: 100%; border-collapse: collapse; }
.feat-table td { padding: 7px 10px; border-bottom: 1px solid #f1f5f9; }
.feat-table td:first-child { color: #64748b; font-family: monospace; font-size: 0.82rem; }
.feat-table td:last-child  { text-align: right; font-weight: 500; }

/* Quality */
.quality-row { display: flex; gap: 24px; flex-wrap: wrap; }
.quality-item { flex: 1; min-width: 120px; }
.quality-item .q-val { font-size: 1.4rem; font-weight: 700; color: #0f172a; }
.quality-item .q-lbl { font-size: 0.78rem; color: #94a3b8; margin-top: 2px; }
.flag { display: inline-block; background: #fef2f2; color: #b91c1c;
        border: 1px solid #fecaca;
        font-size: 0.72rem; border-radius: 4px; padding: 2px 6px; margin-top: 6px; }

/* Scene grid */
.scene-grid { overflow-x: auto; }
table.scenes { border-collapse: collapse; min-width: 100%; }
table.scenes th { padding: 7px 8px; text-align: left; color: #94a3b8;
                  font-size: 0.75rem; font-weight: 600; border-bottom: 2px solid #e2e8f0; }
table.scenes td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9;
                  vertical-align: middle; }
table.scenes tr:hover td { background: #f8fafc; }
table.scenes td:first-child { font-family: monospace; font-size: 0.78rem; color: #64748b;
                               white-space: nowrap; padding-right: 12px; }
table.scenes img { display: block; width: 96px; height: 96px;
                   image-rendering: pixelated; border-radius: 4px;
                   border: 1px solid #e2e8f0; }
.no-img { width: 96px; height: 96px; background: #f8fafc; border: 1px solid #e2e8f0;
          border-radius: 4px; display: flex; align-items: center; justify-content: center;
          color: #94a3b8; font-size: 0.65rem; }

/* Index reference */
.index-ref-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 720px) { .index-ref-grid { grid-template-columns: 1fr; } }
.index-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }
.index-card h3 { font-size: 0.9rem; font-weight: 600; color: #0f172a; margin-bottom: 8px;
                  display: flex; align-items: center; gap: 8px; }
.index-acronym { font-family: monospace; font-size: 0.75rem; background: #dbeafe;
                  padding: 2px 7px; border-radius: 3px; color: #1d4ed8; }
.index-formula { font-family: monospace; font-size: 0.8rem; background: #eff6ff;
                  border: 1px solid #bfdbfe; padding: 7px 10px; border-radius: 4px;
                  color: #1d4ed8; margin-bottom: 8px; white-space: nowrap; overflow-x: auto; }
.index-bands { font-size: 0.74rem; color: #94a3b8; margin-bottom: 8px; }
.index-desc { font-size: 0.81rem; color: #475569; line-height: 1.6; margin-bottom: 10px; }
.index-bar { height: 14px; border-radius: 3px; }
.index-bar-wrap { position: relative; margin-bottom: 20px; }
.index-marker { position: absolute; top: 0; width: 2px; height: 14px;
                transform: translateX(-50%); pointer-events: none; }
.index-marker-label { position: absolute; top: 16px; font-size: 0.6rem;
                      transform: translateX(-50%); white-space: nowrap; font-weight: 600; }
.index-ticks { display: flex; justify-content: space-between;
               font-size: 0.68rem; color: #94a3b8; margin-bottom: 8px; }
.index-ranges { font-size: 0.74rem; margin-bottom: 10px; }
.index-range-row { display: flex; align-items: center; gap: 7px; margin-bottom: 4px; color: #475569; }
.index-swatch { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
.score-badge { display: inline-block; font-size: 0.68rem; padding: 2px 7px; border-radius: 3px;
               font-weight: 500; margin-right: 4px; }
.badge-scoring { background: #dbeafe; color: #1d4ed8; }
.badge-feature { background: #dcfce7; color: #15803d; }

/* Chart */
.chart-wrap { position: relative; height: 260px; }

/* NDWI legend */
.ndwi-legend { margin-top: 16px; }
.ndwi-legend-label { font-size: 0.78rem; color: #64748b; margin-bottom: 6px; }
.ndwi-bar {
  height: 16px; border-radius: 4px;
  background: linear-gradient(to right,
    #a01e1e 0%,        /* -1.0  drought */
    #dcaa6e 35%,       /* -0.3  non-aqueous */
    #ebe1c8 50%,       /* 0.0   boundary */
    #64b4f0 60%,       /* 0.2   flooding/humidity */
    #0028a0 100%       /* 1.0   open water */
  );
}
.ndwi-ticks { display: flex; justify-content: space-between;
              font-size: 0.7rem; color: #94a3b8; margin-top: 3px; }
.ndwi-ranges { display: flex; margin-top: 8px; gap: 8px; flex-wrap: wrap; }
.ndwi-range { display: flex; align-items: center; gap: 5px; font-size: 0.75rem; color: #64748b; }
.ndwi-swatch { width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }

/* No-data */
.no-data { color: #94a3b8; font-style: italic; font-size: 0.85rem; }

/* Feature groups */
.feat-groups { display: flex; flex-direction: column; gap: 10px; }
.feat-group { border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;
              box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.feat-group-hdr { background: #f8fafc; padding: 9px 14px; display: flex; align-items: center;
                  gap: 8px; font-size: 0.8rem; font-weight: 600; color: #64748b;
                  border-bottom: 1px solid #e2e8f0; }
.feat-group-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.feat-group-idx { font-family: monospace; font-size: 0.72rem; background: #dbeafe;
                  padding: 1px 6px; border-radius: 3px; color: #1d4ed8; margin-left: auto; }
.feat-row { display: grid; grid-template-columns: 1fr auto; gap: 20px; align-items: center;
            padding: 11px 14px; border-top: 1px solid #f1f5f9; background: #fff; }
.feat-row:hover { background: #fafafa; }
.feat-label { font-size: 0.84rem; font-weight: 500; color: #1e293b; margin-bottom: 2px; }
.feat-desc { font-size: 0.74rem; color: #64748b; line-height: 1.5; }
.feat-val-col { text-align: right; min-width: 90px; flex-shrink: 0; }
.feat-val { font-size: 1.05rem; font-weight: 700; font-family: monospace; line-height: 1.2; }
.feat-key-mono { font-size: 0.62rem; color: #cbd5e1; font-family: monospace; margin-top: 3px; }
.feat-mini-bg { height: 3px; background: #e2e8f0; border-radius: 2px; margin-top: 5px; }
.feat-mini-fill { height: 3px; border-radius: 2px; }
"""

_CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"


def _bar_with_markers(gradient: str, metric: str, index_stats: dict) -> str:
    """Render an index gradient bar wrapped in a relative container.

    If ``index_stats`` contains min/max for the metric, vertical marker lines are
    overlaid at the corresponding positions (orange = min, green = max).
    All indices use the fixed [-1, 1] scale, so position% = (v + 1) / 2 * 100.
    """
    bar = f'<div class="index-bar" style="background: {gradient}"></div>'
    stats = index_stats.get(metric)
    markers = ""
    if stats:
        for key, label, color in (
            ("min", "min", "#f97316"),
            ("max", "max", "#22c55e"),
        ):
            v = stats.get(key)
            if v is not None:
                pct = max(1.0, min(99.0, (v + 1) / 2 * 100))
                markers += (
                    f'<div class="index-marker"'
                    f' style="left:{pct:.1f}%;background:{color}"></div>'
                    f'<div class="index-marker-label"'
                    f' style="left:{pct:.1f}%;color:{color}">{v:+.2f}&nbsp;{label}</div>'
                )
    return f'<div class="index-bar-wrap">{bar}{markers}</div>'


def _index_reference_html(index_stats: dict) -> str:
    """Build the comprehensive Index Reference section for the report."""
    ndvi_bar = _bar_with_markers(
        "linear-gradient(to right, #6543211a 0%, #654321 5%, #dcd2a0 50%, #bedd50 65%, #3ca028 80%, #004600 100%)",
        "ndvi", index_stats,
    )
    ndwi_bar = _bar_with_markers(
        "linear-gradient(to right, #a01e1e 0%, #ebe1c8 50%, #64b4f0 60%, #0028a0 100%)",
        "ndwi", index_stats,
    )
    ndmi_bar = _bar_with_markers(
        "linear-gradient(to right, #8c320f 0%, #dc8c3c 40%, #f5ebb9 50%, #a0d764 60%, #1e9150 80%, #005a64 100%)",
        "ndmi", index_stats,
    )
    nbr_bar = _bar_with_markers(
        "linear-gradient(to right, #190f0a 0%, #5f5041 45%, #cdb982 55%, #b4d74b 65%, #004b0f 100%)",
        "nbr", index_stats,
    )
    ndsi_bar = _bar_with_markers(
        "linear-gradient(to right, #64411900 0%, #644119 0%, #cdaf6e 50%, #aad7f5 70%, #f5fcff 100%)",
        "ndsi", index_stats,
    )
    bsi_bar = _bar_with_markers(
        "linear-gradient(to right, #005014 0%, #9bcd50 45%, #ebe1b9 50%, #cda55a 65%, #733f14 100%)",
        "bsi", index_stats,
    )

    return f"""
<div class="index-ref-grid">

  <!-- NDVI -->
  <div class="index-card">
    <h3>Normalized Difference Vegetation Index <span class="index-acronym">NDVI</span></h3>
    <div class="index-formula">(B08 &minus; B04) / (B08 + B04)</div>
    <div class="index-bands">Bands: B08 NIR 835nm &bull; B04 Red 665nm &mdash; both 10m resolution</div>
    <p class="index-desc">
      The foundational vegetation index. Exploits the contrast between high NIR reflectance
      from healthy leaf cell structure and strong red absorption by chlorophyll. Values rise
      with vegetation density and greenness. Saturates above ~0.8 in dense closed-canopy forests.
      Used to track long-term vegetation health trends, anomalous stress events, and canopy cover.
    </p>
    {ndvi_bar}
    <div class="index-ticks"><span>&minus;1</span><span>0</span><span>0.3</span><span>0.6</span><span>1</span></div>
    <div class="index-ranges">
      <div class="index-range-row"><div class="index-swatch" style="background:#004600"></div>&gt; 0.6 &mdash; Dense forest / high biomass</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#3ca028"></div>0.3 &ndash; 0.6 &mdash; Moderate to good vegetation</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#bedd50"></div>0.1 &ndash; 0.3 &mdash; Grass, shrub, sparse cover</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#dcd2a0"></div>&minus;0.1 &ndash; 0.1 &mdash; Bare soil, rock, sand</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#654321"></div>&lt; &minus;0.1 &mdash; Water, snow, clouds</div>
    </div>
    <span class="score-badge badge-scoring">Drought score</span>
    <span class="score-badge badge-scoring">Heat mitigation score</span>
    <span class="score-badge badge-scoring">Canopy deficit (composite)</span>
  </div>

  <!-- NDWI -->
  <div class="index-card">
    <h3>Normalized Difference Water Index <span class="index-acronym">NDWI</span></h3>
    <div class="index-formula">(B03 &minus; B08) / (B03 + B08)</div>
    <div class="index-bands">Bands: B03 Green 560nm &bull; B08 NIR 835nm &mdash; both 10m resolution</div>
    <p class="index-desc">
      McFeeters (1996) open-water detection index. Green wavelengths maximize reflectance
      of the water surface; NIR is strongly absorbed by water and strongly reflected by
      vegetation, creating a high contrast that isolates water bodies. Not a vegetation
      moisture index (see NDMI for that).
    </p>
    {ndwi_bar}
    <div class="index-ticks"><span>&minus;1</span><span>0</span><span>+0.2</span><span>+1</span></div>
    <div class="index-ranges">
      <div class="index-range-row"><div class="index-swatch" style="background:#0028a0"></div>0.2 &ndash; 1.0 &mdash; Open water surface</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#64b4f0"></div>0.0 &ndash; 0.2 &mdash; Flooding / soil moisture</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#ebe1c8"></div>&minus;0.3 &ndash; 0.0 &mdash; Non-aqueous / moderate drought</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#a01e1e"></div>&minus;1.0 &ndash; &minus;0.3 &mdash; Drought / dry non-aqueous</div>
    </div>
    <span class="score-badge badge-scoring">Wetness score</span>
    <span class="score-badge badge-feature">ndwi_wetness_persistence_5y</span>
  </div>

  <!-- NDMI -->
  <div class="index-card">
    <h3>Normalized Difference Moisture Index <span class="index-acronym">NDMI</span></h3>
    <div class="index-formula">(B08 &minus; B11) / (B08 + B11)</div>
    <div class="index-bands">Bands: B08 NIR 835nm (10m) &bull; B11 SWIR1 1610nm (20m)</div>
    <p class="index-desc">
      Measures leaf and canopy water content directly. SWIR at 1610nm corresponds to a
      strong liquid-water absorption band, so reflectance drops as leaf water content
      increases. Unlike NDWI, NDMI is sensitive to moisture <em>within vegetation</em> rather
      than open water bodies. An early drought indicator: NDMI drops before NDVI responds.
      Positive = adequate moisture; negative = water stress.
    </p>
    {ndmi_bar}
    <div class="index-ticks"><span>&minus;1</span><span>&minus;0.2</span><span>0</span><span>0.2</span><span>0.6</span><span>1</span></div>
    <div class="index-ranges">
      <div class="index-range-row"><div class="index-swatch" style="background:#005a64"></div>0.4 &ndash; 1.0 &mdash; High moisture / lush canopy</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#1e9150"></div>0.1 &ndash; 0.4 &mdash; Adequate moisture</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#f5ebb9"></div>&minus;0.1 &ndash; 0.1 &mdash; Marginal / transition</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#dc8c3c"></div>&minus;0.3 &ndash; &minus;0.1 &mdash; Moderate water stress</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#8c320f"></div>&lt; &minus;0.3 &mdash; Severe water stress</div>
    </div>
    <span class="score-badge badge-scoring">Drought score</span>
    <span class="score-badge badge-feature">ndmi_moisture_stress_freq_5y</span>
  </div>

  <!-- NBR -->
  <div class="index-card">
    <h3>Normalized Burn Ratio <span class="index-acronym">NBR</span></h3>
    <div class="index-formula">(B08 &minus; B12) / (B08 + B12)</div>
    <div class="index-bands">Bands: B08 NIR 835nm (10m) &bull; B12 SWIR2 2190nm (20m)</div>
    <p class="index-desc">
      Designed to detect and quantify wildfire burn severity. Healthy vegetation has high NIR
      and low SWIR2 reflectance, giving high positive NBR values. Burned areas and char have
      low NIR (destroyed cells) and high SWIR2 (exposed soil minerals), driving NBR sharply
      negative. Also used to track post-fire recovery: NBR rises as vegetation regenerates.
      The differenced NBR (pre minus post-fire) quantifies net burn severity.
    </p>
    {nbr_bar}
    <div class="index-ticks"><span>&minus;1</span><span>&minus;0.1</span><span>0.1</span><span>0.3</span><span>1</span></div>
    <div class="index-ranges">
      <div class="index-range-row"><div class="index-swatch" style="background:#004b0f"></div>&gt; 0.3 &mdash; Healthy unburned vegetation</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#b4d74b"></div>0.1 &ndash; 0.3 &mdash; Low-severity burn / recovering</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#cdb982"></div>&minus;0.1 &ndash; 0.1 &mdash; Moderate burn / bare</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#5f5041"></div>&minus;0.4 &ndash; &minus;0.1 &mdash; High-severity burn</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#190f0a"></div>&lt; &minus;0.4 &mdash; Severely burned / charred</div>
    </div>
    <span class="score-badge badge-scoring">Fire exposure score</span>
    <span class="score-badge badge-feature">nbr_burn_freq_5y</span>
  </div>

  <!-- NDSI -->
  <div class="index-card">
    <h3>Normalized Difference Snow Index <span class="index-acronym">NDSI</span></h3>
    <div class="index-formula">(B03 &minus; B11) / (B03 + B11)</div>
    <div class="index-bands">Bands: B03 Green 560nm (10m) &bull; B11 SWIR1 1610nm (20m)</div>
    <p class="index-desc">
      Distinguishes snow and ice from clouds, soil, and vegetation. Snow has very high
      reflectance in visible green but strongly absorbs SWIR energy, creating a distinctive
      high NDSI signal. Clouds also appear bright in green but similarly bright in SWIR,
      keeping their NDSI lower. Threshold of 0.4 reliably separates snow from all other
      land cover types. Important for snowpack monitoring and alpine climate change analysis.
    </p>
    {ndsi_bar}
    <div class="index-ticks"><span>&minus;1</span><span>0</span><span>0.4</span><span>1</span></div>
    <div class="index-ranges">
      <div class="index-range-row"><div class="index-swatch" style="background:#f5fcff"></div>&gt; 0.6 &mdash; Deep snow / ice</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#aad7f5"></div>0.4 &ndash; 0.6 &mdash; Snow-covered (detection threshold)</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#cdaf6e"></div>0.0 &ndash; 0.4 &mdash; Bare soil / possible patchy snow</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#644119"></div>&lt; 0.0 &mdash; Vegetation / dark surfaces</div>
    </div>
    <span class="score-badge badge-feature">ndsi_snow_persistence_5y</span>
  </div>

  <!-- BSI -->
  <div class="index-card">
    <h3>Bare Soil Index <span class="index-acronym">BSI</span></h3>
    <div class="index-formula">(B11 + B04 &minus; B08 &minus; B02) / (B11 + B04 + B08 + B02)</div>
    <div class="index-bands">Bands: B11 SWIR1 1610nm (20m) &bull; B04 Red 665nm &bull; B08 NIR 835nm &bull; B02 Blue 490nm</div>
    <p class="index-desc">
      Multi-band index that combines SWIR and Red (which highlight soil mineral properties)
      against NIR and Blue (which suppress vegetation and shadow). The combination enhances
      exposed bare soil and suppresses vegetated areas more effectively than any single-band
      ratio. Positive values indicate bare or sparsely covered ground; negative values
      indicate vegetation. Useful as a land degradation and desertification indicator.
    </p>
    {bsi_bar}
    <div class="index-ticks"><span>&minus;1</span><span>&minus;0.1</span><span>0</span><span>0.3</span><span>1</span></div>
    <div class="index-ranges">
      <div class="index-range-row"><div class="index-swatch" style="background:#005014"></div>&lt; &minus;0.2 &mdash; Dense vegetation cover</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#9bcd50"></div>&minus;0.2 &ndash; 0.0 &mdash; Sparse vegetation / mixed</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#cda55a"></div>0.0 &ndash; 0.3 &mdash; Partially exposed soil</div>
      <div class="index-range-row"><div class="index-swatch" style="background:#733f14"></div>&gt; 0.3 &mdash; Heavily bare / degraded ground</div>
    </div>
    <span class="score-badge badge-feature">bsi_bare_soil_freq_5y</span>
    <span class="score-badge badge-feature">bsi_mean_5y</span>
  </div>

</div>"""


def _score_bar(label: str, value: int | None, suppressed: bool = False, inverted: bool = False) -> str:
    """Render a sub-score bar with value-based color coding.

    inverted=True  (heat mitigation): higher is safer -- green ≥60, amber ≥30, red <30.
    inverted=False (drought, wetness, fire): higher is riskier -- green <25, amber <50, orange <75, red ≥75.
    Both cases use the same color for the value number and bar fill.
    """
    if suppressed:
        return (
            f'<div class="score-item">'
            f'<label>{label}</label>'
            f'<div class="value" style="color:#94a3b8;font-size:1rem">N/A</div>'
            f'<div style="font-size:0.72rem;color:#94a3b8;margin-top:4px">Not applicable &mdash; urban location</div>'
            f'</div>'
        )
    if value is None:
        return f'<div class="score-item"><label>{label}</label><div class="value">—</div></div>'
    pct = max(0, min(100, value))
    if inverted:
        color = "#16a34a" if value >= 60 else ("#d97706" if value >= 30 else "#dc2626")
    else:
        color = "#16a34a" if value < 25 else ("#d97706" if value < 50 else ("#ea580c" if value < 75 else "#dc2626"))
    return f"""
    <div class="score-item">
      <label>{label}</label>
      <div class="value" style="color:{color}">{value}</div>
      <div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>
    </div>"""


# ── Feature metadata ──────────────────────────────────────────────────────────
# Each entry: label, group, group_color, group_index, desc, fmt, signal, thr1, thr2
# fmt: "pct" | "slope" | "float3" | "score"
# signal: "high_good" | "low_good" | "context"
# For high_good: v >= thr2 → green, thr1 <= v < thr2 → amber, v < thr1 → red
# For low_good:  v <= thr1 → green, thr1 < v <= thr2 → amber, v > thr2 → red
_FM: dict[str, dict] = {
    "ndvi_mean_5y": dict(
        label="Average vegetation density",
        group="Vegetation Health", group_color="#22c55e", group_index="NDVI",
        desc="Mean NDVI across all valid observations over 5 years. "
             "Dense healthy vegetation: &gt;0.4 &bull; Sparse cover: 0.1&ndash;0.4 &bull; Bare ground or water: &lt;0.1.",
        fmt="float3", signal="high_good", thr1=0.1, thr2=0.4,
    ),
    "ndvi_trend_slope_5y": dict(
        label="Vegetation trend",
        group="Vegetation Health", group_color="#22c55e", group_index="NDVI",
        desc="Theil&ndash;Sen robust slope of NDVI over 5 years (units per year). "
             "Negative = declining vegetation density. Small positive = stable recovery.",
        fmt="slope", signal="high_good", thr1=-0.005, thr2=0.0,
    ),
    "ndvi_anomaly_freq_5y": dict(
        label="Drought anomaly frequency",
        group="Vegetation Health", group_color="#22c55e", group_index="NDVI",
        desc="Share of months where NDVI fell more than 0.1 NDVI units below its seasonal baseline. "
             "Below 10%: occasional stress &bull; 10&ndash;30%: recurring anomalies &bull; above 30%: frequent drought.",
        fmt="pct", signal="low_good", thr1=0.1, thr2=0.3,
    ),
    "ndwi_wetness_persistence_5y": dict(
        label="Open-water persistence",
        group="Open Water", group_color="#3b82f6", group_index="NDWI",
        desc="Share of months with open water detected (NDWI &gt; 0, McFeeters). "
             "Below 20%: dry land &bull; 20&ndash;50%: seasonal flooding or riparian influence &bull; above 50%: near-permanent water. "
             "Context-dependent: expected to be high for wetlands and floodplains.",
        fmt="pct", signal="context", thr1=0.2, thr2=0.5,
    ),
    "ndmi_mean_5y": dict(
        label="Average vegetation moisture",
        group="Vegetation Moisture", group_color="#06b6d4", group_index="NDMI",
        desc="Mean NDMI across 5 years. Positive values indicate adequate leaf water content; "
             "negative values indicate chronic moisture deficit within the canopy.",
        fmt="float3", signal="high_good", thr1=-0.1, thr2=0.1,
    ),
    "ndmi_moisture_stress_freq_5y": dict(
        label="Moisture stress frequency",
        group="Vegetation Moisture", group_color="#06b6d4", group_index="NDMI",
        desc="Share of months where vegetation water stress was detected (NDMI &lt; 0). "
             "Below 10%: well-watered &bull; 10&ndash;30%: moderate recurring deficit &bull; above 30%: significant chronic stress. "
             "Contributes directly to the drought risk sub-score.",
        fmt="pct", signal="low_good", thr1=0.1, thr2=0.3,
    ),
    "nbr_mean_5y": dict(
        label="Average burn ratio",
        group="Fire History", group_color="#f97316", group_index="NBR",
        desc="Mean NBR over 5 years. Healthy unburned vegetation typically exceeds 0.3. "
             "Low or negative values indicate sustained fire damage or bare mineral soil.",
        fmt="float3", signal="high_good", thr1=0.1, thr2=0.3,
    ),
    "nbr_burn_freq_5y": dict(
        label="Burn signal frequency",
        group="Fire History", group_color="#f97316", group_index="NBR",
        desc="Share of months where a burn signal was present (NBR &lt; 0.1). "
             "Above 5%: notable fire history &bull; above 15%: recurrent fire events. "
             "Directly sets the fire exposure score.",
        fmt="pct", signal="low_good", thr1=0.05, thr2=0.15,
    ),
    "ndsi_snow_persistence_5y": dict(
        label="Snow-cover persistence",
        group="Snow Cover", group_color="#a5f3fc", group_index="NDSI",
        desc="Share of months with snow detected (NDSI &gt; 0.4). "
             "Below 10%: rare snow &bull; 10&ndash;40%: seasonal snowpack &bull; above 40%: persistent snow cover. "
             "Note: open water bodies can produce high NDSI values similar to snow &mdash; "
             "high readings at low elevations may indicate water, not snowpack.",
        fmt="pct", signal="context", thr1=0.1, thr2=0.4,
    ),
    "bsi_mean_5y": dict(
        label="Average bare soil exposure",
        group="Bare Soil", group_color="#d97706", group_index="BSI",
        desc="Mean BSI over 5 years. Positive values indicate bare or degraded ground is dominant; "
             "negative values indicate vegetated surfaces suppressing the soil signal.",
        fmt="float3", signal="low_good", thr1=0.0, thr2=0.2,
    ),
    "bsi_bare_soil_freq_5y": dict(
        label="Bare soil frequency",
        group="Bare Soil", group_color="#d97706", group_index="BSI",
        desc="Share of months with bare soil dominant (BSI &gt; 0). "
             "Below 10%: well-vegetated &bull; 10&ndash;30%: mixed or seasonal exposure &bull; above 30%: dominantly bare. "
             "Can reflect land degradation, erosion risk, or seasonal tillage patterns.",
        fmt="pct", signal="low_good", thr1=0.1, thr2=0.3,
    ),
    "canopy_proxy": dict(
        label="Canopy density",
        group="Canopy & Context", group_color="#4ade80", group_index="NDVI",
        desc="Peak-season NDVI averaged over the location's growing season. "
             "Proxies tree cover, shading potential, and micro-climate buffering. "
             "Drives the heat mitigation sub-score.",
        fmt="float3", signal="high_good", thr1=0.2, thr2=0.4,
    ),
    "quality_score": dict(
        label="Data quality",
        group="Quality", group_color="#9ca3af", group_index=None,
        desc="Composite 0&ndash;100 score based on scene coverage, cloud fraction, and valid pixel ratio. "
             "Below 50: low confidence &mdash; features may be unreliable.",
        fmt="score", signal="high_good", thr1=0.4, thr2=0.7,
    ),
    "sar_water_freq_5y": dict(
        label="SAR flood frequency (chronic)",
        group="SAR Flood", group_color="#06b6d4", group_index=None,
        desc="Fraction of Sentinel-1 SAR scenes (snow months excluded) flagged as flooded "
             "by an orbit-stratified, MAD-based detector. Each Sentinel-1 orbital pass is evaluated "
             "independently using its own adaptive threshold (median + 2&times;MAD, min 5%); the highest "
             "frequency across orbits is reported. Cloud-independent: SAR penetrates clouds, detecting "
             "flood events invisible to optical sensors. Chronic metric: measures long-term recurrence. "
             "Below 5%: near-zero flood history &bull; 5&ndash;15%: seasonal or episodic flooding &bull; "
             "above 15%: recurrent flood exposure. "
             "Threshold: empirical DN&nbsp;75 (~above noise floor, well below vegetated land).",
        fmt="pct", signal="low_good", thr1=0.05, thr2=0.15,
    ),
    # TerraClimate features (University of Idaho, ~4 km, monthly, 1958–2024)
    "tmax_mean_5y": dict(
        label="Average maximum temperature",
        group="Climate (TerraClimate)", group_color="#f43f5e", group_index=None,
        desc="Mean monthly maximum temperature (°C) from TerraClimate over the analysis window. "
             "Context: tropical &gt;30°C &bull; temperate 15&ndash;25°C &bull; polar &lt;5°C.",
        fmt="temp", signal="context", thr1=20.0, thr2=30.0,
    ),
    "tmax_summer_mean_5y": dict(
        label="Growing-season max temperature",
        group="Climate (TerraClimate)", group_color="#f43f5e", group_index=None,
        desc="Mean maximum temperature during the growing season (May&ndash;Sep temperate, "
             "Mar&ndash;Nov subtropical). Reflects peak heat load on vegetation.",
        fmt="temp", signal="context", thr1=25.0, thr2=35.0,
    ),
    "tmax_anomaly_freq_5y": dict(
        label="Heat anomaly frequency",
        group="Climate (TerraClimate)", group_color="#f43f5e", group_index=None,
        desc="Fraction of months where max temperature exceeded the historical monthly mean by "
             "more than 1 standard deviation. Higher = more frequent heat anomalies. "
             "Contributes to the heat stress sub-score.",
        fmt="pct", signal="low_good", thr1=0.15, thr2=0.30,
    ),
    "tmax_trend_slope_5y": dict(
        label="Temperature warming trend",
        group="Climate (TerraClimate)", group_color="#f43f5e", group_index=None,
        desc="Theil&ndash;Sen robust slope of monthly maximum temperature (°C/year). "
             "Positive = warming. Above 0.05°C/yr is a notable trend at local scale.",
        fmt="temp_slope", signal="low_good", thr1=0.02, thr2=0.05,
    ),
    "tmin_mean_5y": dict(
        label="Average minimum temperature",
        group="Climate (TerraClimate)", group_color="#f43f5e", group_index=None,
        desc="Mean monthly minimum temperature (°C). Indicates overnight cooling and frost risk. "
             "Context only: high values suggest urban heat island or tropical climate.",
        fmt="temp", signal="context", thr1=5.0, thr2=20.0,
    ),
    "ppt_annual_mean_5y": dict(
        label="Mean annual precipitation",
        group="Climate (TerraClimate)", group_color="#3b82f6", group_index=None,
        desc="Mean annual precipitation total (mm) from TerraClimate monthly sums. "
             "Context: arid &lt;250 mm &bull; semi-arid 250&ndash;500 mm &bull; "
             "humid &gt;750 mm.",
        fmt="mm", signal="context", thr1=250.0, thr2=750.0,
    ),
    "vpd_mean_5y": dict(
        label="Average vapor pressure deficit",
        group="Climate (TerraClimate)", group_color="#f97316", group_index=None,
        desc="Mean monthly vapor pressure deficit (kPa). VPD drives plant water demand and "
             "fire weather. &lt;0.5 kPa: humid &bull; 0.5&ndash;1.5 kPa: moderate &bull; "
             "&gt;1.5 kPa: high stress.",
        fmt="vpd", signal="low_good", thr1=0.5, thr2=1.5,
    ),
    "vpd_high_freq_5y": dict(
        label="High-VPD frequency",
        group="Climate (TerraClimate)", group_color="#f97316", group_index=None,
        desc="Fraction of months with VPD &gt; 1.5 kPa (high atmospheric drought stress). "
             "Contributes to the heat stress sub-score. "
             "Below 15%: rare stress &bull; 15&ndash;30%: recurring &bull; above 30%: chronic.",
        fmt="pct", signal="low_good", thr1=0.15, thr2=0.30,
    ),
    "pdsi_mean_5y": dict(
        label="Average PDSI",
        group="Climate (TerraClimate)", group_color="#d97706", group_index=None,
        desc="Mean Palmer Drought Severity Index. Negative = drier than normal, positive = wetter. "
             "&lt;&minus;2: moderate drought &bull; &lt;&minus;3: severe &bull; "
             "&lt;&minus;4: extreme. Scale: &minus;10 to +10.",
        fmt="pdsi", signal="context", thr1=-2.0, thr2=0.0,
    ),
    "pdsi_drought_freq_5y": dict(
        label="PDSI drought frequency",
        group="Climate (TerraClimate)", group_color="#d97706", group_index=None,
        desc="Fraction of months with PDSI &lt; &minus;2 (moderate drought or worse). "
             "Directly contributes to the drought sub-score (weight 0.25). "
             "Below 10%: occasional &bull; 10&ndash;25%: recurring &bull; above 25%: chronic drought.",
        fmt="pct", signal="low_good", thr1=0.10, thr2=0.25,
    ),
    "sar_flood_anomaly": dict(
        label="SAR flood anomaly (acute event)",
        group="SAR Flood", group_color="#06b6d4", group_index=None,
        desc="Peak excess water coverage in recent scenes (last 2 calendar months) vs the historical "
             "median for the same calendar month across prior years. Uses <em>all</em> SAR scenes &mdash; "
             "not affected by snow/flood NDSI confusion that can suppress the chronic metric. "
             "Detects sudden flood events even in winter months. "
             "Below 10%: within seasonal norm &bull; 10&ndash;30%: notable wet anomaly &bull; "
             "above 30%: acute flood signal detected.",
        fmt="pct", signal="low_good", thr1=0.10, thr2=0.30,
    ),
}

_GROUP_ORDER = [
    "Vegetation Health",
    "Open Water",
    "Vegetation Moisture",
    "Fire History",
    "Snow Cover",
    "Bare Soil",
    "Canopy & Context",
    "SAR Flood",
    "Climate (TerraClimate)",
    "Quality",
    "Other",
]


def _fmt_feat_value(v: float, fmt: str) -> str:
    if fmt == "pct":
        return f"{v * 100:.1f}%"
    if fmt == "slope":
        return f"{v:+.4f} / yr"
    if fmt == "score":
        return f"{v * 100:.0f} / 100"
    if fmt == "temp":
        return f"{v:.1f} °C"
    if fmt == "temp_slope":
        return f"{v:+.3f} °C/yr"
    if fmt == "mm":
        return f"{v:.0f} mm/yr"
    if fmt == "vpd":
        return f"{v:.2f} kPa"
    if fmt == "pdsi":
        return f"{v:+.2f}"
    return f"{v:+.3f}"  # float3


def _feat_color(v: float, signal: str, thr1: float, thr2: float) -> str:
    """Return a CSS hex color for the value given the signal direction and thresholds."""
    if signal == "context":
        return "#64748b"
    if signal == "high_good":
        return "#16a34a" if v >= thr2 else ("#d97706" if v >= thr1 else "#dc2626")
    # low_good
    return "#16a34a" if v <= thr1 else ("#d97706" if v <= thr2 else "#dc2626")


def _mini_bar(v: float, fmt: str, color: str) -> str:
    """Small horizontal fill bar for pct / score features."""
    if fmt not in ("pct", "score"):
        return ""
    pct = min(100.0, v * 100)
    return (
        f'<div class="feat-mini-bg">'
        f'<div class="feat-mini-fill" style="width:{pct:.1f}%;background:{color}"></div>'
        f'</div>'
    )


# Feature groups where vegetation-based signals are unreliable on impervious surfaces
_URBAN_SUPPRESSED_GROUPS = {"Vegetation Health", "Vegetation Moisture", "Fire History"}

# Keys to omit from the feature table (shown elsewhere in the report)
_FEAT_SKIP = {"is_urban"}


def _features_html(features: dict, is_urban: bool = False) -> str:
    """Render the Derived Features section as grouped, annotated cards."""
    if not features:
        return '<p class="no-data">No features computed yet.</p>'

    # Bucket features into groups (preserving _GROUP_ORDER), skipping control keys
    grouped: dict[str, list[tuple[str, float]]] = {g: [] for g in _GROUP_ORDER}
    for k, v in features.items():
        if k in _FEAT_SKIP:
            continue
        if not isinstance(v, (int, float)):
            continue
        meta = _FM.get(k)
        group = meta["group"] if meta else "Other"
        grouped.setdefault(group, []).append((k, float(v)))

    parts = ['<div class="feat-groups">']
    for group_name in _GROUP_ORDER:
        rows = grouped.get(group_name, [])
        if not rows:
            continue

        first_meta = next((_FM[k] for k, _ in rows if k in _FM), None)
        g_color = first_meta["group_color"] if first_meta else "#6b7280"
        g_index = first_meta.get("group_index") if first_meta else None
        idx_badge = (
            f'<span class="feat-group-idx">{g_index}</span>' if g_index else ""
        )

        # Urban notice for suppressed groups
        urban_notice = ""
        if is_urban and group_name in _URBAN_SUPPRESSED_GROUPS:
            g_color = "#cbd5e1"  # dim the group header
            urban_notice = (
                '<div style="padding:6px 14px;font-size:0.74rem;color:#64748b;'
                'background:#f8fafc;border-bottom:1px solid #e2e8f0">'
                'Values reflect impervious surfaces, not vegetation. '
                'These signals are suppressed in the risk scores for this urban location.'
                '</div>'
            )

        parts.append(
            f'<div class="feat-group">'
            f'<div class="feat-group-hdr">'
            f'<span class="feat-group-dot" style="background:{g_color}"></span>'
            f'{group_name}{idx_badge}'
            f'</div>'
            f'{urban_notice}'
        )

        for k, v in rows:
            meta = _FM.get(k)
            if meta:
                label = meta["label"]
                desc = f'<div class="feat-desc">{meta["desc"]}</div>'
                fmt = meta["fmt"]
                # Gray out color coding for urban-suppressed groups
                if is_urban and group_name in _URBAN_SUPPRESSED_GROUPS:
                    color = "#4b5563"
                else:
                    color = _feat_color(v, meta["signal"], meta["thr1"], meta["thr2"])
                val_str = _fmt_feat_value(v, fmt)
                bar = _mini_bar(v, fmt, color)
            else:
                label = k.replace("_", " ")
                desc = ""
                color = "#9ca3af"
                val_str = f"{v:.4f}"
                bar = ""

            parts.append(
                f'<div class="feat-row">'
                f'<div class="feat-info">'
                f'<div class="feat-label">{label}</div>'
                f'{desc}'
                f'</div>'
                f'<div class="feat-val-col">'
                f'<div class="feat-val" style="color:{color}">{val_str}</div>'
                f'{bar}'
                f'<div class="feat-key-mono">{k}</div>'
                f'</div>'
                f'</div>'
            )

        parts.append('</div>')

    parts.append('</div>')
    return "\n".join(parts)


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
        "ndmi": {"border": "#06b6d4", "bg": "rgba(6,182,212,0.12)"},
        "nbr":  {"border": "#f97316", "bg": "rgba(249,115,22,0.12)"},
        "ndsi": {"border": "#a5f3fc", "bg": "rgba(165,243,252,0.12)"},
        "bsi":  {"border": "#d97706", "bg": "rgba(217,119,6,0.12)"},
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
        return '<tr><td colspan="9" class="no-data">No scene images cached yet.</td></tr>'
    rows = []
    for entry in scene_months:
        month = entry["month_key"]
        bands = entry["bands"]
        nir   = bands.get("B08")
        red   = bands.get("B04")
        green = bands.get("B03")
        swir  = bands.get("B11")
        swir2 = bands.get("B12")
        blue  = bands.get("B02")

        def img_or_empty(b64: str | None, alt: str) -> str:
            if b64:
                return f'<img src="data:image/png;base64,{b64}" alt="{alt}">'
            return f'<div class="no-img">{alt}</div>'

        b04_b64  = band_to_b64(red)                          if red is not None else None
        b08_b64  = band_to_b64(nir)                          if nir is not None else None
        ndvi_b64 = ndvi_to_b64(nir, red)            if (nir is not None and red is not None) else None
        ndwi_b64 = ndwi_to_b64(green, nir)          if (green is not None and nir is not None) else None
        ndmi_b64 = ndmi_to_b64(nir, swir)           if (nir is not None and swir is not None) else None
        nbr_b64  = nbr_to_b64(nir, swir2)           if (nir is not None and swir2 is not None) else None
        ndsi_b64 = ndsi_to_b64(green, swir)         if (green is not None and swir is not None) else None
        bsi_b64  = bsi_to_b64(swir, red, nir, blue) if (swir is not None and red is not None and nir is not None and blue is not None) else None

        rows.append(f"""
        <tr>
          <td>{month}</td>
          <td>{img_or_empty(b04_b64,  'B04')}</td>
          <td>{img_or_empty(b08_b64,  'B08')}</td>
          <td>{img_or_empty(ndvi_b64, 'NDVI')}</td>
          <td>{img_or_empty(ndwi_b64, 'NDWI')}</td>
          <td>{img_or_empty(ndmi_b64, 'NDMI')}</td>
          <td>{img_or_empty(nbr_b64,  'NBR')}</td>
          <td>{img_or_empty(ndsi_b64, 'NDSI')}</td>
          <td>{img_or_empty(bsi_b64,  'BSI')}</td>
        </tr>""")
    return "\n".join(rows)


def _sar_scene_rows(sar_scene_months: list[dict], water_threshold: int) -> str:
    if not sar_scene_months:
        return '<tr><td colspan="3" class="no-data">No SAR scene images cached yet.</td></tr>'
    from ..config import settings as _s
    rows = []
    for entry in sar_scene_months:
        month = entry["month_key"]
        vv_dn = entry["vv_dn"]
        water_frac = entry.get("water_frac")
        frac_str = f"{water_frac * 100:.1f}%" if water_frac is not None else "—"
        vv_b64 = vv_dn_to_b64(vv_dn, water_threshold)
        rows.append(f"""
        <tr>
          <td>{month}</td>
          <td><img src="data:image/png;base64,{vv_b64}" alt="VV {month}"></td>
          <td style="font-family:monospace;font-size:0.82rem">{frac_str}</td>
        </tr>""")
    return "\n".join(rows)


def _sar_frac_chart_html(
    sar_scene_fracs: list[tuple[str, float, int]],
    burn_months: set[str] | None = None,
) -> str:
    """Chart.js bar chart of SAR water fraction per scene with per-orbit adaptive thresholds.

    Bars are colored by relative orbit (two orbits = blue / orange).
    Burn-suppressed months are shown in amber -- their SAR signal is excluded from the
    chronic water frequency because post-fire bare soil mimics low-backscatter water.
    Each orbit gets its own dashed threshold line at max(median + 2×MAD, 5%).
    """
    from collections import defaultdict
    from statistics import median as _median

    if not sar_scene_fracs:
        return '<p class="no-data">No SAR water fraction data available.</p>'

    from ..config import settings as _cfg
    mad_k = _cfg.SAR_FLOOD_MAD_K
    min_anomaly = _cfg.SAR_MIN_ANOMALY_FRACTION

    # Palette: (bar opaque, bar faint, line color) per orbit index
    _palette = [
        ("rgba(30,100,220,0.75)",  "rgba(30,100,220,0.25)",  "#1e64dc"),  # blue
        ("rgba(234,88,12,0.75)",   "rgba(234,88,12,0.25)",   "#ea580c"),  # orange
        ("rgba(22,163,74,0.75)",   "rgba(22,163,74,0.25)",   "#16a34a"),  # green
    ]

    # Ordered unique orbits (preserves first-seen order = chronological)
    unique_orbits: list[int] = list(dict.fromkeys(o for _, _, o in sar_scene_fracs))
    orbit_idx = {o: i for i, o in enumerate(unique_orbits)}

    # Per-orbit MAD-based adaptive threshold
    by_orbit: dict[int, list[float]] = defaultdict(list)
    for _, wf, o in sar_scene_fracs:
        by_orbit[o].append(wf)

    def _mad(fracs: list[float], loc_med: float) -> float:
        return _median(abs(f - loc_med) for f in fracs)

    orbit_thr: dict[int, float] = {}
    for o, fracs in by_orbit.items():
        loc_med = _median(fracs)
        mad_val = _mad(fracs, loc_med)
        orbit_thr[o] = round(min(max(loc_med + mad_k * mad_val, min_anomaly), 1.0) * 100, 1)

    n = len(sar_scene_fracs)
    labels_json = json.dumps([mk for mk, _, _ in sar_scene_fracs])
    data_json   = json.dumps([round(wf * 100, 2) for _, wf, _ in sar_scene_fracs])

    # Bar colors: amber for burn-suppressed months, else opaque/faint by orbit threshold
    _burn_color  = "rgba(217,119,6,0.80)"
    _burn_border = "rgba(217,119,6,1.0)"
    bar_colors = []
    border_colors = []
    border_widths = []
    has_burn = False
    for mk, wf, o in sar_scene_fracs:
        if burn_months and mk in burn_months:
            bar_colors.append(_burn_color)
            border_colors.append(_burn_border)
            border_widths.append(2)
            has_burn = True
        else:
            idx = orbit_idx[o] % len(_palette)
            col_op, col_faint, _ = _palette[idx]
            bar_colors.append(col_op if wf * 100 >= orbit_thr[o] else col_faint)
            border_colors.append("rgba(0,0,0,0.08)")
            border_widths.append(0.5)
    colors_json = json.dumps(bar_colors)

    # One threshold dataset per orbit
    thr_datasets: list[dict] = []
    for o in unique_orbits:
        idx = orbit_idx[o] % len(_palette)
        _, _, line_col = _palette[idx]
        thr_pct = orbit_thr[o]
        label = f"Orbit {o} threshold ({thr_pct}%)"
        thr_datasets.append({
            "label": label,
            "data": [thr_pct] * n,
            "type": "line",
            "borderColor": line_col,
            "borderDash": [5, 4],
            "borderWidth": 1.5,
            "pointRadius": 0,
            "fill": False,
            "tension": 0,
            "order": 1,
        })

    datasets_json = json.dumps([
        {
            "label": "Water fraction %",
            "data": json.loads(data_json),
            "backgroundColor": bar_colors,
            "borderColor": border_colors,
            "borderWidth": border_widths,
            "order": 2,
        },
        *thr_datasets,
    ])

    burn_legend = (
        '<div style="margin-top:8px;font-size:0.72rem;color:#92400e;display:flex;align-items:center;gap:6px">'
        '<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
        'background:rgba(217,119,6,0.80);border:2px solid rgba(217,119,6,1.0);flex-shrink:0"></span>'
        'Amber bars: burn-suppressed months &mdash; post-fire bare soil mimics low SAR backscatter. '
        'Excluded from chronic flood frequency.'
        '</div>'
    ) if has_burn else ""

    return f"""
    <div class="chart-wrap" style="height:220px;margin-bottom:6px">
      <canvas id="sarFracChart"></canvas>
    </div>
    {burn_legend}
    <script>
    new Chart(document.getElementById('sarFracChart'), {{
      type: 'bar',
      data: {{
        labels: {labels_json},
        datasets: {datasets_json},
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ labels: {{ color: '#64748b' }} }} }},
        scales: {{
          x: {{ ticks: {{ color: '#94a3b8', maxTicksLimit: 18, maxRotation: 45 }},
                grid: {{ color: '#f1f5f9' }} }},
          y: {{ min: 0, max: 100,
                ticks: {{ color: '#94a3b8', callback: function(v) {{ return v + '%'; }} }},
                grid: {{ color: '#f1f5f9' }},
                title: {{ display: true, text: 'Water fraction (%)', color: '#94a3b8' }} }}
        }}
      }}
    }});
    </script>"""


def _tc_climate_charts_html(
    tc_monthly: dict[str, list[tuple[int, int, float | None]]] | None,
) -> str:
    """Render TerraClimate temperature and precipitation/VPD charts.

    Parameters
    ----------
    tc_monthly:
        {variable: [(year, month, value), ...]} as returned by
        store.get_all_terraclimate_for_grid().
    """
    if not tc_monthly:
        return '<p class="no-data">TerraClimate data not available for this location.</p>'

    import json as _json

    def _month_label(year: int, month: int) -> str:
        return f"{year}-{month:02d}"

    def _series_to_monthly(
        data: list[tuple[int, int, float | None]],
    ) -> tuple[list[str], list[float | None]]:
        """Convert [(year, month, value), ...] to aligned (labels, values) lists."""
        points = sorted(data, key=lambda t: (t[0], t[1]))
        labels = [_month_label(y, m) for y, m, _ in points]
        values = [v for _, _, v in points]
        return labels, values

    tmax_data = tc_monthly.get("tmax", [])
    tmin_data = tc_monthly.get("tmin", [])
    ppt_data  = tc_monthly.get("ppt", [])
    vpd_data  = tc_monthly.get("vpd", [])

    has_temp = bool(tmax_data or tmin_data)
    has_ppt  = bool(ppt_data)
    has_vpd  = bool(vpd_data)

    if not has_temp and not has_ppt and not has_vpd:
        return '<p class="no-data">TerraClimate data not available for this location.</p>'

    parts: list[str] = []

    # ── Temperature chart (tmax + tmin line) ──────────────────────────────────
    if has_temp:
        if tmax_data:
            t_labels, tmax_vals = _series_to_monthly(tmax_data)
        elif tmin_data:
            t_labels, _ = _series_to_monthly(tmin_data)
            tmax_vals = [None] * len(t_labels)
        if tmin_data:
            _, tmin_vals = _series_to_monthly(tmin_data)
            if len(tmin_vals) < len(t_labels):
                tmin_vals = tmin_vals + [None] * (len(t_labels) - len(tmin_vals))
        else:
            tmin_vals = [None] * len(t_labels)

        temp_datasets = [
            {
                "label": "Tmax (°C)",
                "data": tmax_vals,
                "borderColor": "#ef4444",
                "backgroundColor": "rgba(239,68,68,0.08)",
                "fill": False,
                "tension": 0.3,
                "spanGaps": True,
                "pointRadius": 2,
            },
            {
                "label": "Tmin (°C)",
                "data": tmin_vals,
                "borderColor": "#3b82f6",
                "backgroundColor": "rgba(59,130,246,0.08)",
                "fill": False,
                "tension": 0.3,
                "spanGaps": True,
                "pointRadius": 2,
            },
        ]
        labels_json = _json.dumps(t_labels)
        datasets_json = _json.dumps(temp_datasets)
        parts.append(f"""
        <div style="margin-bottom:8px;font-size:0.78rem;font-weight:600;color:#64748b">
          Maximum &amp; Minimum Temperature
        </div>
        <div class="chart-wrap" style="height:220px;margin-bottom:24px">
          <canvas id="tcTempChart"></canvas>
        </div>
        <script>
        new Chart(document.getElementById('tcTempChart'), {{
          type: 'line',
          data: {{ labels: {labels_json}, datasets: {datasets_json} }},
          options: {{
            responsive: true, maintainAspectRatio: false,
            plugins: {{ legend: {{ labels: {{ color: '#64748b' }} }} }},
            scales: {{
              x: {{ ticks: {{ color: '#94a3b8', maxTicksLimit: 18, maxRotation: 45 }},
                    grid: {{ color: '#f1f5f9' }} }},
              y: {{ ticks: {{ color: '#94a3b8',
                              callback: function(v) {{ return v + ' °C'; }} }},
                    grid: {{ color: '#f1f5f9' }},
                    title: {{ display: true, text: 'Temperature (°C)', color: '#94a3b8' }} }}
            }}
          }}
        }});
        </script>""")

    # ── Precipitation + VPD chart (PPT bars + VPD line, dual axis) ────────────
    if has_ppt or has_vpd:
        if ppt_data:
            pv_labels, ppt_vals = _series_to_monthly(ppt_data)
        else:
            pv_labels, _ = _series_to_monthly(vpd_data)
            ppt_vals = [None] * len(pv_labels)
        if vpd_data:
            _, vpd_vals = _series_to_monthly(vpd_data)
            if len(vpd_vals) < len(pv_labels):
                vpd_vals = vpd_vals + [None] * (len(pv_labels) - len(vpd_vals))
        else:
            vpd_vals = [None] * len(pv_labels)

        pv_labels_json = _json.dumps(pv_labels)
        ppt_vals_json  = _json.dumps(ppt_vals)
        vpd_vals_json  = _json.dumps(vpd_vals)
        parts.append(f"""
        <div style="margin-bottom:8px;font-size:0.78rem;font-weight:600;color:#64748b">
          Precipitation (mm) &amp; Vapor Pressure Deficit (kPa)
        </div>
        <div class="chart-wrap" style="height:220px">
          <canvas id="tcPptVpdChart"></canvas>
        </div>
        <script>
        new Chart(document.getElementById('tcPptVpdChart'), {{
          data: {{
            labels: {pv_labels_json},
            datasets: [
              {{
                type: 'bar',
                label: 'Precipitation (mm)',
                data: {ppt_vals_json},
                backgroundColor: 'rgba(59,130,246,0.45)',
                borderColor: 'rgba(59,130,246,0.7)',
                borderWidth: 0.5,
                yAxisID: 'yPpt',
                order: 2,
              }},
              {{
                type: 'line',
                label: 'VPD (kPa)',
                data: {vpd_vals_json},
                borderColor: '#f97316',
                backgroundColor: 'rgba(249,115,22,0.10)',
                fill: false,
                tension: 0.3,
                spanGaps: true,
                pointRadius: 2,
                yAxisID: 'yVpd',
                order: 1,
              }},
            ]
          }},
          options: {{
            responsive: true, maintainAspectRatio: false,
            plugins: {{ legend: {{ labels: {{ color: '#64748b' }} }} }},
            scales: {{
              x: {{ ticks: {{ color: '#94a3b8', maxTicksLimit: 18, maxRotation: 45 }},
                    grid: {{ color: '#f1f5f9' }} }},
              yPpt: {{
                type: 'linear', position: 'left',
                ticks: {{ color: '#3b82f6', callback: function(v) {{ return v + ' mm'; }} }},
                grid: {{ color: '#f1f5f9' }},
                title: {{ display: true, text: 'Precip (mm)', color: '#3b82f6' }}
              }},
              yVpd: {{
                type: 'linear', position: 'right',
                ticks: {{ color: '#f97316', callback: function(v) {{ return v + ' kPa'; }} }},
                grid: {{ drawOnChartArea: false }},
                title: {{ display: true, text: 'VPD (kPa)', color: '#f97316' }}
              }},
            }}
          }}
        }});
        </script>""")

    return "\n".join(parts)


def build_report_html(
    location_key: str,
    name: str | None,
    centroid: list[float] | None,
    geometry_geojson: dict | None,
    scores: dict | None,
    features: dict | None,
    quality: dict | None,
    timeseries: dict[str, list[dict]] | None,
    scene_months: list[dict],
    processing_version: str,
    score_version: str,
    climate: dict | None = None,
    sar_scene_months: list[dict] | None = None,
    sar_scene_fracs: list[tuple[str, float, int]] | None = None,
    tc_monthly: dict[str, list[tuple[int, int, float | None]]] | None = None,
    burn_months: set[str] | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    key_short = location_key[:24] + "..." if len(location_key) > 24 else location_key
    date_range_str = (
        f"{date_start} to {date_end}"
        if date_start and date_end
        else None
    )

    display_name = name or "Unnamed location"
    if centroid:
        lon, lat = centroid
        coord_str = f"{lat:+.5f}, {lon:+.5f}"
    else:
        coord_str = "—"

    # Climate badge
    if climate:
        code = climate.get("code", "")
        label = climate.get("label", code)
        criterion = climate.get("criterion", "")
        climate_html = (
            f'<span title="{criterion}" style="'
            f'display:inline-flex;align-items:center;gap:6px;'
            f'background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;'
            f'padding:3px 10px;font-size:0.82rem;color:#1e293b;cursor:default">'
            f'<span style="font-weight:700;color:#2563eb;font-family:monospace;font-size:1rem">{code}</span>'
            f'<span style="color:#94a3b8">&mdash;</span>'
            f'<span>{label}</span>'
            f'</span>'
        )
    else:
        climate_html = ""

    # Thumbnail
    thumb_url = f"/v1/thumbnail/{location_key}.png"
    if geometry_geojson:
        thumb_html = f'<img src="{thumb_url}" alt="Location map" onerror="this.parentNode.innerHTML=\'<div class=&quot;no-thumb&quot;>Thumbnail unavailable</div>\'">'
    else:
        thumb_html = '<div class="no-thumb">No geometry stored</div>'

    # Urban flag
    feat = features or {}
    is_urban = (feat.get("is_urban") or 0.0) > 0.5

    # Scores
    s = scores or {}
    composite = s.get("composite_score")

    # Risk level label and color for composite score
    if composite is not None:
        if composite < 25:
            risk_label, risk_color = "Low risk", "#16a34a"
        elif composite < 50:
            risk_label, risk_color = "Moderate risk", "#d97706"
        elif composite < 75:
            risk_label, risk_color = "Elevated risk", "#ea580c"
        else:
            risk_label, risk_color = "High risk", "#dc2626"
        risk_badge = (
            f'<span style="display:inline-block;font-size:0.78rem;font-weight:600;'
            f'color:{risk_color};background:{risk_color}18;border:1px solid {risk_color}44;'
            f'border-radius:4px;padding:2px 9px;margin-left:10px;vertical-align:middle">'
            f'{risk_label}</span>'
        )
    else:
        risk_badge = ""

    _composite_color = risk_color if composite is not None else "#6b7280"
    composite_html = (
        f'<div style="display:flex;align-items:baseline;gap:4px;flex-wrap:wrap">'
        f'<div style="font-size:2.2rem;font-weight:800;color:{_composite_color}">{composite if composite is not None else "—"}</div>'
        f'<span style="color:#94a3b8;font-size:0.82rem;align-self:flex-end;padding-bottom:6px">'
        f'/ 100</span>'
        f'{risk_badge}'
        f'</div>'
        f'<div style="font-size:0.74rem;color:#64748b;margin-top:6px;line-height:1.5">'
        f'Higher score = more climate risk. Scale: '
        f'<span style="color:#16a34a">0&ndash;24 low</span> &bull; '
        f'<span style="color:#d97706">25&ndash;49 moderate</span> &bull; '
        f'<span style="color:#ea580c">50&ndash;74 elevated</span> &bull; '
        f'<span style="color:#dc2626">75&ndash;100 high</span>'
        f'</div>'
    )

    score_bars = (
        _score_bar("Drought", s.get("drought_score"), suppressed=is_urban) +
        _score_bar("Wetness", s.get("wetness_score")) +
        _score_bar("Fire exposure", s.get("fire_exposure_score"), suppressed=is_urban) +
        _score_bar("Flood risk (SAR)", s.get("flood_risk_score")) +
        _score_bar("Heat stress (TerraClimate)", s.get("heat_stress_score")) +
        _score_bar("Heat mitigation (higher = more canopy = safer)", s.get("heat_mitigation_score"), inverted=True)
    )

    # Urban banner + formula note
    _pill = (
        'display:inline-block;font-size:0.72rem;font-weight:500;'
        'border-radius:3px;padding:1px 7px;margin:2px 3px 2px 0'
    )
    if is_urban:
        urban_banner = (
            '<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;'
            'padding:10px 14px;margin-bottom:16px">'
            '<div style="font-size:0.82rem;font-weight:600;color:#1d4ed8;margin-bottom:6px">'
            'Urban / Impervious Surface Detected</div>'
            '<div style="font-size:0.74rem;color:#475569;line-height:1.8">'
            'Drought and fire scores are suppressed (not applicable on impervious surfaces).<br>'
            'Composite = '
            f'<span style="{_pill};background:#dcfce7;color:#15803d">60% canopy deficit</span>'
            '(= 100 &minus; heat mitigation) + '
            f'<span style="{_pill};background:#dbeafe;color:#1d4ed8">15% wetness</span>'
            '(flooding / waterlogging) + '
            f'<span style="{_pill};background:#cffafe;color:#0e7490">15% flood risk</span>'
            '(SAR water frequency) + '
            f'<span style="{_pill};background:#fef3c7;color:#92400e">10% heat stress</span>'
            '(TerraClimate)'
            '</div>'
            '</div>'
        )
        formula_note = ""
    else:
        urban_banner = ""
        _climate_code = climate.get("code") if climate else None
        _w = climate_weights_for_code(_climate_code)
        _profile = climate_profile_label(_climate_code)
        formula_note = (
            '<div style="font-size:0.72rem;color:#64748b;margin-bottom:14px;line-height:1.8">'
            f'Composite <span style="color:#94a3b8;font-style:italic">({_profile} profile)</span> = '
            f'<span style="{_pill};background:#fee2e2;color:#b91c1c">{_w["drought"]:.0%} drought</span>'
            f'<span style="{_pill};background:#dbeafe;color:#1d4ed8">{_w["wetness"]:.0%} wetness</span>'
            f'<span style="{_pill};background:#ffedd5;color:#c2410c">{_w["fire"]:.0%} fire</span>'
            f'<span style="{_pill};background:#dcfce7;color:#15803d">{_w["heat_inv"]:.0%} canopy deficit</span>'
            f'<span style="{_pill};background:#cffafe;color:#0e7490">{_w.get("flood", 0.12):.0%} flood</span>'
            f'<span style="{_pill};background:#fef3c7;color:#92400e">{_w.get("heat_stress", 0.20):.0%} heat stress</span>'
            '<br><span style="color:#94a3b8">Canopy deficit = 100 &minus; heat mitigation score. '
            'Low canopy raises the composite risk.</span>'
            '</div>'
        )

    # Quality
    q = quality or {}
    months_total = q.get("months_total", "—")
    months_observed = q.get("months_observed", "—")
    cloud_frac = q.get("mean_cloud_fraction")
    cloud_pct = f"{cloud_frac * 100:.1f}%" if cloud_frac is not None else "—"
    flags = q.get("flags", [])
    flag_html = "".join(f'<span class="flag">{f}</span> ' for f in flags) if flags else ""

    coverage_ratio = (
        months_observed / months_total
        if isinstance(months_observed, int) and isinstance(months_total, int) and months_total > 0
        else None
    )
    coverage_pct = f"{coverage_ratio * 100:.0f}%" if coverage_ratio is not None else "—"

    # Color thresholds -- same palette as score bars
    # Coverage / months observed: higher = better
    if coverage_ratio is None:
        _cov_color = "#0f172a"
    elif coverage_ratio >= 0.80:
        _cov_color = "#16a34a"   # green
    elif coverage_ratio >= 0.50:
        _cov_color = "#d97706"   # amber
    else:
        _cov_color = "#dc2626"   # red

    # Cloud fraction: lower = better (inverted)
    if cloud_frac is None:
        _cloud_color = "#0f172a"
    elif cloud_frac <= 0.20:
        _cloud_color = "#16a34a"
    elif cloud_frac <= 0.40:
        _cloud_color = "#d97706"
    else:
        _cloud_color = "#dc2626"

    # Feature rows
    features_html = _features_html(feat, is_urban=is_urban)

    # Per-index min/max from timeseries (used by the index reference legend bars)
    index_stats: dict[str, dict] = {}
    if timeseries:
        for metric, records in timeseries.items():
            vals = [r.get("mean") for r in records if r.get("mean") is not None]
            if vals:
                index_stats[metric] = {"min": round(min(vals), 3), "max": round(max(vals), 3)}

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
            plugins: {{ legend: {{ labels: {{ color: '#64748b' }} }} }},
            scales: {{
              x: {{ ticks: {{ color: '#94a3b8', maxTicksLimit: 12 }},
                    grid: {{ color: '#f1f5f9' }} }},
              y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#f1f5f9' }},
                    title: {{ display: true, text: 'Index value', color: '#94a3b8' }} }}
            }}
          }}
        }});
        </script>
        """
    else:
        chart_html = '<p class="no-data">No time series stored yet. Call /v1/location/timeseries first.</p>'

    # TerraClimate climate charts
    tc_chart_html = _tc_climate_charts_html(tc_monthly)

    # Scene image rows
    scene_rows = _scene_rows(scene_months)

    # SAR scene rows
    from ..config import settings as _cfg
    sar_rows = _sar_scene_rows(sar_scene_months or [], _cfg.SAR_WATER_DN_THRESHOLD)

    # SAR water fraction chart
    sar_frac_chart = _sar_frac_chart_html(sar_scene_fracs or [], burn_months=burn_months)

    # Flood alert banner (shown when acute anomaly is elevated)
    flood_anomaly_val = feat.get("sar_flood_anomaly") or 0.0
    if flood_anomaly_val > 0.30:
        _al_color, _al_bg = "#dc2626", "#fef2f2"
        _al_title = "Acute flood event detected"
    elif flood_anomaly_val > 0.10:
        _al_color, _al_bg = "#ea580c", "#fff7ed"
        _al_title = "Elevated SAR flood anomaly"
    else:
        _al_color = _al_bg = _al_title = ""
    if _al_title:
        flood_alert_html = (
            f'<div style="background:{_al_bg};border:1px solid {_al_color}44;border-radius:6px;'
            f'padding:10px 14px;margin-bottom:14px">'
            f'<div style="font-size:0.85rem;font-weight:600;color:{_al_color}">{_al_title}</div>'
            f'<div style="font-size:0.76rem;color:#64748b;margin-top:4px">'
            f'SAR water coverage anomaly: {flood_anomaly_val * 100:.1f}% above seasonal baseline. '
            f'Recent SAR scenes show significantly higher water fraction than historical norm '
            f'for the same calendar months.'
            f'</div>'
            f'</div>'
        )
    else:
        flood_alert_html = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{display_name} &mdash; Location Report</title>
  <script src="{_CHART_JS_CDN}"></script>
  <style>{_CSS}</style>
</head>
<body>

<div class="header">
  <h1>{display_name}</h1>
  <div style="margin-top:6px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
    <span style="color:#64748b;font-size:0.9rem">&#x1F4CD; {coord_str}</span>
    {climate_html}
    <small style="color:#94a3b8;font-size:0.75rem;font-family:monospace">{location_key}</small>
  </div>
  <div style="margin-top:4px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
    <span style="color:#94a3b8;font-size:0.72rem">generated {generated}</span>
    {f'<span style="color:#64748b;font-size:0.76rem">&#x1F4C5; Analysis period: <strong>{date_range_str}</strong></span>' if date_range_str else ''}
  </div>
</div>

<div class="container">

  <!-- Overview -->
  <div class="grid-2">
    <div class="card thumbnail">{thumb_html}</div>
    <div class="card">
      <h2>Composite score</h2>
      {urban_banner}
      {composite_html}
      <div style="margin-top:20px">
        <h2>Sub-scores</h2>
        {formula_note}
        <div class="scores">{score_bars}</div>
      </div>
    </div>
  </div>

  <!-- Quality -->
  <div class="card">
    <h2>Data quality</h2>
    <div class="quality-row">
      <div class="quality-item">
        <div class="q-val" style="color:{_cov_color}">{months_observed} / {months_total}</div>
        <div class="q-lbl">Months observed</div>
      </div>
      <div class="quality-item">
        <div class="q-val" style="color:{_cov_color}">{coverage_pct}</div>
        <div class="q-lbl">Coverage</div>
      </div>
      <div class="quality-item">
        <div class="q-val" style="color:{_cloud_color}">{cloud_pct}</div>
        <div class="q-lbl">Mean cloud fraction</div>
      </div>
      <div class="quality-item">
        <div class="q-val" style="font-size:0.9rem">{flag_html or '&mdash;'}</div>
        <div class="q-lbl">Flags</div>
      </div>
    </div>
    <div style="margin-top:12px;color:#94a3b8;font-size:0.78rem">
      Processing: {processing_version} &nbsp;&bull;&nbsp; Score: {score_version}
    </div>
    <div style="margin-top:14px;padding:10px 14px;background:#fafafa;border:1px solid #e2e8f0;border-radius:6px;font-size:0.74rem;color:#64748b;line-height:1.7">
      <strong style="color:#475569">Disclaimer.</strong>
      All scores and feature estimates are based on satellite imagery sampled over the period
      {f'<strong>{date_range_str}</strong>' if date_range_str else 'the requested analysis window'}.
      Results depend on scene availability, cloud cover, and spectral index retrieval quality.
      Satellite-derived indices may be affected by atmospheric conditions, terrain effects,
      mixed land-cover within the observation window, and sensor artifacts.
      Scores are statistical summaries of remotely sensed signals and do not constitute
      a certified risk assessment. Interpretation should account for local context
      and be validated against ground truth where appropriate.
    </div>
  </div>

  <!-- TerraClimate -->
  <div class="card">
    <h2>Climate context (TerraClimate ~4 km monthly)</h2>
    <div style="font-size:0.75rem;color:#94a3b8;margin-bottom:14px">
      University of Idaho Climatology Lab &mdash; 1/24° global grid.
      Data retrieved from THREDDS OPeNDAP (single grid cell, no imagery download).
    </div>
    {tc_chart_html}
  </div>

  <!-- Time series chart -->
  <div class="card">
    <h2>Time series</h2>
    {chart_html}
  </div>

  <!-- Features -->
  <div class="card">
    <h2>Derived features</h2>
    {features_html}
  </div>

  

  <!-- Index Reference -->
  <div class="card">
    <h2>Index reference</h2>
    {_index_reference_html(index_stats)}
  </div>

  <!-- S2 Scene images -->
  <div class="card">
    <h2>Sentinel-2 scenes (most recent {len(scene_months)})</h2>
    <div class="scene-grid">
      <table class="scenes">
        <thead>
          <tr>
            <th>Month</th>
            <th>B04 Red</th>
            <th>B08 NIR</th>
            <th>NDVI</th>
            <th>NDWI</th>
            <th>NDMI</th>
            <th>NBR</th>
            <th>NDSI</th>
            <th>BSI</th>
          </tr>
        </thead>
        <tbody>{scene_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- SAR Flood Analysis -->
  <div class="card">
    <h2>Sentinel-1 SAR &mdash; Flood Analysis</h2>
    {flood_alert_html}
    <div style="font-size:0.76rem;color:#64748b;margin-bottom:10px">
      Water fraction per SAR scene (chronological), colored by Sentinel-1 relative orbit.
      Dashed lines show the per-orbit adaptive flood threshold: max(median&nbsp;+&nbsp;2&times;MAD,&nbsp;5%).
      Opaque bar = scene above its orbit's threshold; faint = below.
    </div>
    {sar_frac_chart}
    <h2 style="margin-top:20px;margin-bottom:12px">SAR scene images (most recent {len(sar_scene_months or [])})</h2>
    <div style="font-size:0.76rem;color:#64748b;margin-bottom:12px">
      VV backscatter &mdash; log-scaled grayscale. Blue pixels: DN &lt; {_cfg.SAR_WATER_DN_THRESHOLD} (water threshold).
      Dark = calm water / specular &bull; Bright = vegetation / urban / rough terrain.
    </div>
    <div class="scene-grid">
      <table class="scenes">
        <thead>
          <tr>
            <th>Month</th>
            <th>VV backscatter</th>
            <th>Water fraction</th>
          </tr>
        </thead>
        <tbody>{sar_rows}</tbody>
      </table>
    </div>
  </div>

</div>
</body>
</html>"""
