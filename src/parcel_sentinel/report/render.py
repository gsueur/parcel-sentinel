from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

# NDVI colormap: 5 stops mapped to t in [0, 1] where t = (ndvi + 1) / 2
# ndvi=-1 → t=0.00 → dark brown (bare rock / water)
# ndvi=0  → t=0.50 → beige       (sparse / soil)
# ndvi=0.3→ t=0.65 → yellow-green (low veg)
# ndvi=0.6→ t=0.80 → medium green (moderate veg)
# ndvi=1  → t=1.00 → dark green   (dense veg)
_NDVI_STOPS_T = np.array([0.00, 0.50, 0.65, 0.80, 1.00], dtype=np.float32)
_NDVI_STOPS_RGB = np.array([
    [101,  67,  33],   # dark brown
    [220, 210, 160],   # beige
    [190, 220,  80],   # yellow-green
    [ 60, 160,  40],   # medium green
    [  0,  70,   0],   # dark green
], dtype=np.float32)


def _build_ndvi_lut() -> np.ndarray:
    """Pre-build a 256×3 uint8 lookup table for the NDVI colormap."""
    lut = np.zeros((256, 3), dtype=np.uint8)
    ts = np.linspace(0.0, 1.0, 256)
    for i, t in enumerate(ts):
        # Find bracketing stops
        idx = np.searchsorted(_NDVI_STOPS_T, t, side="right") - 1
        idx = int(np.clip(idx, 0, len(_NDVI_STOPS_T) - 2))
        t0, t1 = _NDVI_STOPS_T[idx], _NDVI_STOPS_T[idx + 1]
        alpha = (t - t0) / (t1 - t0 + 1e-9)
        rgb = _NDVI_STOPS_RGB[idx] * (1 - alpha) + _NDVI_STOPS_RGB[idx + 1] * alpha
        lut[i] = np.clip(rgb, 0, 255).astype(np.uint8)
    return lut


_NDVI_LUT = _build_ndvi_lut()


# NDWI (McFeeters) colormap: 5 stops mapped to t in [0, 1] where t = (ndwi + 1) / 2
# ndwi=-1.0 → t=0.00 → deep red    (severe drought)
# ndwi=-0.3 → t=0.35 → tan/beige   (non-aqueous transition)
# ndwi= 0.0 → t=0.50 → pale        (boundary)
# ndwi= 0.2 → t=0.60 → light blue  (flooding / humidity)
# ndwi= 1.0 → t=1.00 → deep blue   (open water)
_NDWI_STOPS_T = np.array([0.00, 0.35, 0.50, 0.60, 1.00], dtype=np.float32)
_NDWI_STOPS_RGB = np.array([
    [160,  30,  30],   # deep red      (drought)
    [220, 170, 110],   # tan/beige     (non-aqueous)
    [235, 225, 200],   # pale          (zero boundary)
    [100, 180, 240],   # light blue    (flooding/humidity)
    [  0,  40, 160],   # deep blue     (open water)
], dtype=np.float32)


def _build_ndwi_lut() -> np.ndarray:
    """Pre-build a 256×3 uint8 lookup table for the NDWI colormap."""
    lut = np.zeros((256, 3), dtype=np.uint8)
    ts = np.linspace(0.0, 1.0, 256)
    for i, t in enumerate(ts):
        idx = np.searchsorted(_NDWI_STOPS_T, t, side="right") - 1
        idx = int(np.clip(idx, 0, len(_NDWI_STOPS_T) - 2))
        t0, t1 = _NDWI_STOPS_T[idx], _NDWI_STOPS_T[idx + 1]
        alpha = (t - t0) / (t1 - t0 + 1e-9)
        rgb = _NDWI_STOPS_RGB[idx] * (1 - alpha) + _NDWI_STOPS_RGB[idx + 1] * alpha
        lut[i] = np.clip(rgb, 0, 255).astype(np.uint8)
    return lut


_NDWI_LUT = _build_ndwi_lut()


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _to_b64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")


def band_to_b64(arr: np.ndarray, scale: int = 4) -> str:
    """Render a 2D float array as a grayscale PNG (percentile-clipped), return base64."""
    arr = np.nan_to_num(arr.astype(np.float32), nan=0.0)
    p2, p98 = np.percentile(arr, [2, 98])
    if p98 > p2:
        arr = np.clip((arr - p2) / (p98 - p2), 0, 1)
    else:
        arr = np.zeros_like(arr)
    pixels = (arr * 255).astype(np.uint8)
    img = Image.fromarray(pixels, mode="L")
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    return _to_b64(_to_png_bytes(img))


def ndwi_to_b64(green: np.ndarray, nir: np.ndarray, scale: int = 4) -> str:
    """Compute NDWI (McFeeters) from GREEN and NIR arrays and render with the NDWI colormap."""
    green = green.astype(np.float32)
    nir = nir.astype(np.float32)
    denom = green + nir
    with np.errstate(invalid="ignore", divide="ignore"):
        ndwi = np.where(denom > 0, (green - nir) / denom, np.nan)
    ndwi = np.nan_to_num(ndwi, nan=0.0)
    # Map ndwi [-1, 1] → lut index [0, 255]
    idx = np.clip(((ndwi + 1) / 2 * 255).astype(np.int32), 0, 255)
    rgb = _NDWI_LUT[idx]  # (H, W, 3)
    img = Image.fromarray(rgb, mode="RGB")
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    return _to_b64(_to_png_bytes(img))


def ndvi_to_b64(nir: np.ndarray, red: np.ndarray, scale: int = 4) -> str:
    """Compute NDVI from NIR and RED arrays and render with the NDVI colormap."""
    nir = nir.astype(np.float32)
    red = red.astype(np.float32)
    denom = nir + red
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)
    ndvi = np.nan_to_num(ndvi, nan=0.0)
    # Map ndvi [-1, 1] → lut index [0, 255]
    idx = np.clip(((ndvi + 1) / 2 * 255).astype(np.int32), 0, 255)
    rgb = _NDVI_LUT[idx]  # (H, W, 3)
    img = Image.fromarray(rgb, mode="RGB")
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    return _to_b64(_to_png_bytes(img))
