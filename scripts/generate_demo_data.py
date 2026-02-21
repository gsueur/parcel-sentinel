"""Generate timeseries + features + score for 20 diverse US/Canada locations."""
from __future__ import annotations

import asyncio
import sys
import time

import httpx

BASE = "http://localhost:8000/v1"
DATE_START = "2021-01-01"
DATE_END   = "2026-02-21"

# connect quickly, but allow up to 5 min for a cold 62-month pipeline
TIMEOUT = httpx.Timeout(300.0, connect=10.0)

LOCATIONS = [
    # name,                          lon,         lat
    ("Central Park",              -73.9654,   40.7829),  # urban park, NYC
    ("Napa Valley Vineyard",     -122.2654,   38.5025),  # wine country, CA
    ("Yellowstone Meadow",       -110.5885,   44.4280),  # volcanic plateau, WY
    ("Florida Everglades",        -80.8987,   25.6866),  # subtropical wetland
    ("Sonoran Desert",           -110.9747,   32.2226),  # hot desert, AZ
    ("Mississippi Delta Farm",    -90.8789,   33.5207),  # agriculture, MS
    ("Cascades Old Growth",      -121.5362,   47.8021),  # temperate rainforest, WA
    ("Kansas Wheat Belt",         -99.3314,   38.8673),  # great plains farm
    ("Chesapeake Wetland",        -76.4823,   38.7904),  # tidal marsh, MD
    ("Vancouver Island Forest",  -124.9274,   49.6557),  # BC coast rainforest
    ("Saskatchewan Prairie",     -105.0372,   51.5347),  # canadian prairies
    ("Laurentian Forest",         -72.9765,   47.8321),  # boreal, Quebec
    ("Vermont Maple Forest",      -72.5778,   44.5588),  # northern hardwood
    ("Louisiana Bayou",           -90.0715,   29.9511),  # Gulf coast swamp
    ("Texas Hill Country",        -99.7337,   30.0460),  # oak savanna
    ("Montana Rangeland",        -110.3626,   46.8797),  # northern plains
    ("Mojave Desert",            -115.9150,   35.1725),  # hot arid, CA
    ("Canadian Rockies",         -115.5708,   51.1784),  # alpine, Alberta
    ("Appalachian Forest",        -82.8579,   35.6933),  # southern highlands, NC
    ("Prince Edward Island Farm", -63.1311,   46.2382),  # maritime agriculture
]


async def process_location(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    customer_id: str,
    name: str,
    lon: float,
    lat: float,
    idx: int,
) -> None:
    async with sem:
        t0 = time.monotonic()
        geom = {"type": "Point", "coordinates": [lon, lat]}
        base = {"name": name, "customer_id": customer_id, "geometry": geom}

        print(f"[{idx:02d}/20] {name:<30} starting …", flush=True)
        try:
            # Timeseries — also warms the DuckDB band cache
            r = await client.post(f"{BASE}/location/timeseries", json={
                **base,
                "date_start": DATE_START,
                "date_end": DATE_END,
                "metrics": ["ndvi", "ndwi"],
            })
            r.raise_for_status()
            ts = r.json()
            key = ts["location_key"]
            obs = ts["quality"]["months_observed"]
            tot = ts["quality"]["months_total"]

            # Features — bands already in DuckDB band cache
            r = await client.post(f"{BASE}/location/features", json={
                **base,
                "date_start": DATE_START,
                "date_end": DATE_END,
                "metrics": ["ndvi", "ndwi"],
            })
            r.raise_for_status()

            # Score
            r = await client.post(f"{BASE}/location/score", json={
                **base,
                "date_end": DATE_END,
                "lookback_years": 5,
            })
            r.raise_for_status()
            scores = r.json()["scores"]

            elapsed = time.monotonic() - t0
            print(
                f"[{idx:02d}/20] {name:<30} ✓  key={key}  "
                f"obs={obs}/{tot}  composite={scores['composite_score']}  {elapsed:.0f}s",
                flush=True,
            )

        except httpx.HTTPStatusError as e:
            print(f"[{idx:02d}/20] {name:<30} HTTP {e.response.status_code}: "
                  f"{e.response.text[:200]}", file=sys.stderr, flush=True)
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(f"[{idx:02d}/20] {name:<30} ERR {type(e).__name__}: {e}  {elapsed:.0f}s",
                  file=sys.stderr, flush=True)


async def main() -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{BASE}/customers", json={"name": "US & Canada Demo"})
        r.raise_for_status()
        customer = r.json()
        customer_id = customer["customer_id"]

    print(f"Customer: {customer['name']}  id={customer_id}")
    print(f"Processing {len(LOCATIONS)} locations (2 concurrent) …\n")

    t_total = time.monotonic()
    sem = asyncio.Semaphore(2)  # 2 concurrent pipelines — keeps server load manageable

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        await asyncio.gather(*[
            process_location(client, sem, customer_id, name, lon, lat, i + 1)
            for i, (name, lon, lat) in enumerate(LOCATIONS)
        ])

    print(f"\nDone in {(time.monotonic() - t_total) / 60:.1f} min")
    print(f"Customer page: http://localhost:8000/v1/customers/{customer_id}")
    print(f"All locations: http://localhost:8000/v1/locations?format=html")


if __name__ == "__main__":
    asyncio.run(main())
