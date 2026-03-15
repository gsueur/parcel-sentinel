from __future__ import annotations

import logging
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

# Beck et al. (2023) legend: integer pixel value → Köppen-Geiger code.
_INT_TO_CODE: dict[int, str] = {
    1: "Af",  2: "Am",  3: "Aw",
    4: "BWh", 5: "BWk", 6: "BSh",  7: "BSk",
    8: "Csa", 9: "Csb", 10: "Csc",
    11: "Cwa", 12: "Cwb", 13: "Cwc",
    14: "Cfa", 15: "Cfb", 16: "Cfc",
    17: "Dsa", 18: "Dsb", 19: "Dsc", 20: "Dsd",
    21: "Dwa", 22: "Dwb", 23: "Dwc", 24: "Dwd",
    25: "Dfa", 26: "Dfb", 27: "Dfc", 28: "Dfd",
    29: "ET",  30: "EF",
}

# Lazy singleton -- S3Store is thread-safe and reusable across requests.
_koeppen_store: Any | None = None


def _get_store() -> Any:
    global _koeppen_store
    if _koeppen_store is None:
        from obstore.store import S3Store
        _koeppen_store = S3Store(
            bucket=settings.KOEPPEN_COG_URL.split("/")[2],
            region=settings.KOEPPEN_AWS_REGION,
            # Private bucket: uses AWS credential chain (env vars / instance profile).
            # Do NOT set skip_signature=True.
        )
    return _koeppen_store


async def lookup_climate_cog(lat: float, lon: float) -> str | None:
    """Return the Köppen-Geiger code for (lat, lon) from the Beck et al. 1km COG.

    Reads a single pixel from the global COG via async-geotiff + obstore.
    Returns None on any error (network, credentials, out-of-bounds, no data).
    """
    from async_geotiff import GeoTIFF, Window

    # Object key is everything after "s3://<bucket>/"
    key = "/".join(settings.KOEPPEN_COG_URL.split("/")[3:])

    try:
        geotiff = await GeoTIFF.open(key, store=_get_store())
        # The Beck COG is in EPSG:4326; transform maps pixels → (lon, lat).
        inv = ~geotiff.transform
        col, row = inv * (lon, lat)
        window = Window(
            col_off=int(round(col)),
            row_off=int(round(row)),
            width=1,
            height=1,
        )
        result = await geotiff.read(window=window)
        data = result.data
        if data.ndim == 3:
            data = data[0]
        pixel = int(data[0, 0])
        code = _INT_TO_CODE.get(pixel)
        if code is None:
            logger.warning(
                "Unknown Köppen pixel value %d at (%.4f, %.4f)", pixel, lat, lon
            )
        return code
    except Exception as exc:
        logger.warning("Köppen COG lookup failed for (%.4f, %.4f): %s", lat, lon, exc)
        return None
