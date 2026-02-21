from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

from ..storage.duckdb_store import store

router = APIRouter()

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0f1117; color: #e0e0e0; font-size: 14px; }
.header { padding: 20px 24px 16px; border-bottom: 1px solid #1e2130; }
.header h1 { font-size: 1.3rem; font-weight: 600; color: #fff; }
.header small { color: #6b7280; font-size: 0.8rem; }
.container { max-width: 900px; margin: 0 auto; padding: 24px; }
.card { display: flex; align-items: center; gap: 16px;
        background: #161b27; border: 1px solid #1e2130; border-radius: 8px;
        padding: 16px; margin-bottom: 12px; text-decoration: none;
        transition: border-color 0.15s; }
.card:hover { border-color: #3b82f6; }
.thumb { width: 80px; height: 54px; object-fit: cover; border-radius: 4px;
         background: #1e2130; flex-shrink: 0; }
.thumb-placeholder { width: 80px; height: 54px; border-radius: 4px;
                     background: #1e2130; flex-shrink: 0; }
.info { flex: 1; min-width: 0; }
.name { font-size: 1rem; font-weight: 600; color: #fff;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.coords { font-size: 0.8rem; color: #9ca3af; margin-top: 3px; }
.key  { font-size: 0.72rem; color: #4b5563; font-family: monospace;
        margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.updated { font-size: 0.75rem; color: #4b5563; flex-shrink: 0; text-align: right; }
.empty { color: #4b5563; font-style: italic; padding: 24px 0; }
"""


@router.get("/locations")
async def list_locations(format: str = Query(default="json", pattern="^(json|html)$")):
    """List all stored locations.

    Returns JSON by default. Pass ?format=html for a browsable index page
    with thumbnail previews and links to individual reports.
    """
    locations = store.get_all_locations()

    if format == "html":
        return HTMLResponse(content=_build_html(locations))

    return JSONResponse(content={"count": len(locations), "locations": locations})


def _build_html(locations: list[dict]) -> str:
    if not locations:
        cards = '<p class="empty">No locations computed yet.</p>'
    else:
        rows = []
        for p in locations:
            name = p["name"] or "Unnamed location"
            coords = ""
            if p["centroid"]:
                lon, lat = p["centroid"]
                coords = f"&#x1F4CD; {lat:+.5f}, {lon:+.5f}"
            key_short = p["location_key"][:32] + "..."
            updated = p["updated_at"][:16].replace("T", " ") if p["updated_at"] else ""
            rows.append(f"""
            <a class="card" href="{p['report_url']}">
              <img class="thumb" src="{p['thumbnail_url']}"
                   alt="" onerror="this.className='thumb-placeholder'">
              <div class="info">
                <div class="name">{name}</div>
                <div class="coords">{coords}</div>
                <div class="key">{key_short}</div>
              </div>
              <div class="updated">{updated}</div>
            </a>""")
        cards = "\n".join(rows)

    count = len(locations)
    noun = "location" if count == 1 else "locations"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Location Sentinel &mdash; Locations</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="header">
    <h1>Locations</h1>
    <small>{count} {noun} stored</small>
  </div>
  <div class="container">
    {cards}
  </div>
</body>
</html>"""
