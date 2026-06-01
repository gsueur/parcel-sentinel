from __future__ import annotations

import html

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..auth.dependencies import UserClaims, require_admin
from ..config import settings
from ..storage.duckdb_store import store

router = APIRouter()


class CustomerCreate(BaseModel):
    name: str


# ------------------------------------------------------------------
# JSON endpoints
# ------------------------------------------------------------------

@router.get("/customers")
async def list_customers(_: UserClaims = Depends(require_admin)):
    """List all customers. Admin only."""
    customers = store.get_all_customers()
    return JSONResponse(content={"count": len(customers), "customers": customers})


@router.post("/customers", status_code=201)
async def create_customer(body: CustomerCreate, _: UserClaims = Depends(require_admin)):
    """Create a new customer. Returns a unique 6-hex-char customer_id. Admin only."""
    customer = store.create_customer(body.name)
    return JSONResponse(content=customer, status_code=201)


@router.get("/customers/{customer_id}/locations")
async def get_customer_locations_json(customer_id: str, _: UserClaims = Depends(require_admin)):
    customer = store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    locations = store.get_customer_locations(customer_id)
    return {
        "customer": customer,
        "count": len(locations),
        "server_versions": {
            "processing": settings.PROCESSING_VERSION,
            "score": settings.SCORE_VERSION,
        },
        "locations": locations,
    }


# ------------------------------------------------------------------
# HTML customer page
# ------------------------------------------------------------------

@router.get("/customers/{customer_id}", response_class=HTMLResponse)
async def get_customer_page(customer_id: str, _: UserClaims = Depends(require_admin)):
    """Browsable page showing all locations for a customer. Admin only."""
    customer = store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    locations = store.get_customer_locations(customer_id)
    return HTMLResponse(content=_build_html(customer, locations))


# ------------------------------------------------------------------
# HTML builder
# ------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0f1117; color: #e0e0e0; font-size: 14px; }
.header { padding: 20px 24px 16px; border-bottom: 1px solid #1e2130; }
.header h1 { font-size: 1.3rem; font-weight: 600; color: #fff; }
.header .sub { margin-top: 6px; display: flex; gap: 20px; flex-wrap: wrap; align-items: baseline; }
.header .badge { background: #1e2130; border: 1px solid #2d3348; border-radius: 4px;
                 padding: 2px 8px; font-size: 0.75rem; font-family: monospace; color: #9ca3af; }
.header small { color: #4b5563; font-size: 0.8rem; }
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


def _build_html(customer: dict, locations: list[dict]) -> str:
    count = len(locations)
    noun = "location" if count == 1 else "locations"

    if not locations:
        cards = '<p class="empty">No locations yet for this customer.</p>'
    else:
        rows = []
        for p in locations:
            # User-supplied fields are escaped to prevent stored XSS.
            name = html.escape(p["name"] or "Unnamed location")
            coords = ""
            if p["centroid"]:
                lon, lat = p["centroid"]
                coords = f"&#x1F4CD; {lat:+.5f}, {lon:+.5f}"
            key_short = html.escape(p["location_key"][:32]) + "..."
            updated = p["updated_at"][:16].replace("T", " ") if p["updated_at"] else ""
            rows.append(f"""
            <a class="card" href="{html.escape(p['report_url'], quote=True)}">
              <img class="thumb" src="{html.escape(p['thumbnail_url'], quote=True)}"
                   alt="" onerror="this.className='thumb-placeholder'">
              <div class="info">
                <div class="name">{name}</div>
                <div class="coords">{coords}</div>
                <div class="key">{key_short}</div>
              </div>
              <div class="updated">{updated}</div>
            </a>""")
        cards = "\n".join(rows)

    customer_name = html.escape(customer["name"])
    customer_id_safe = html.escape(customer["customer_id"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{customer_name} &mdash; Location Sentinel</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="header">
    <h1>{customer_name}</h1>
    <div class="sub">
      <span class="badge">ID: {customer_id_safe}</span>
      <small>{count} {noun}</small>
    </div>
  </div>
  <div class="container">
    {cards}
  </div>
</body>
</html>"""
