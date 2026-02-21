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


# --------------------------------------------------------------------------- #
# NDMI colormap: vegetation moisture (B08-B11)/(B08+B11)
# ndmi=-1.0 → t=0.00 → deep brown-red  (severe water stress / dead vegetation)
# ndmi=-0.2 → t=0.40 → orange-tan      (moderate stress)
# ndmi= 0.0 → t=0.50 → pale yellow     (boundary)
# ndmi= 0.2 → t=0.60 → light green     (adequate moisture)
# ndmi= 0.6 → t=0.80 → medium green    (high moisture)
# ndmi= 1.0 → t=1.00 → deep teal       (very high moisture)
# --------------------------------------------------------------------------- #
_NDMI_STOPS_T = np.array([0.00, 0.40, 0.50, 0.60, 0.80, 1.00], dtype=np.float32)
_NDMI_STOPS_RGB = np.array([
    [140,  50,  15],   # deep brown-red   (severe stress)
    [220, 140,  60],   # orange-tan       (moderate stress)
    [245, 235, 185],   # pale yellow      (boundary)
    [160, 215, 100],   # light green      (adequate)
    [ 30, 145,  80],   # medium green     (high moisture)
    [  0,  90, 100],   # deep teal        (very moist)
], dtype=np.float32)


def _build_ndmi_lut() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    ts = np.linspace(0.0, 1.0, 256)
    for i, t in enumerate(ts):
        idx = np.searchsorted(_NDMI_STOPS_T, t, side="right") - 1
        idx = int(np.clip(idx, 0, len(_NDMI_STOPS_T) - 2))
        t0, t1 = _NDMI_STOPS_T[idx], _NDMI_STOPS_T[idx + 1]
        alpha = (t - t0) / (t1 - t0 + 1e-9)
        rgb = _NDMI_STOPS_RGB[idx] * (1 - alpha) + _NDMI_STOPS_RGB[idx + 1] * alpha
        lut[i] = np.clip(rgb, 0, 255).astype(np.uint8)
    return lut


_NDMI_LUT = _build_ndmi_lut()


# --------------------------------------------------------------------------- #
# NBR colormap: normalized burn ratio (B08-B12)/(B08+B12)
# nbr=-1.0 → t=0.00 → charcoal-black   (severely burned)
# nbr=-0.1 → t=0.45 → dark gray        (burned)
# nbr= 0.1 → t=0.55 → tan/beige        (bare / sparse)
# nbr= 0.3 → t=0.65 → yellow-green     (recovering vegetation)
# nbr= 1.0 → t=1.00 → dark forest-green (healthy vegetation)
# --------------------------------------------------------------------------- #
_NBR_STOPS_T = np.array([0.00, 0.45, 0.55, 0.65, 1.00], dtype=np.float32)
_NBR_STOPS_RGB = np.array([
    [ 25,  15,  10],   # charcoal-black   (severely burned)
    [ 95,  80,  65],   # dark gray        (burned)
    [205, 185, 130],   # tan/beige        (bare/sparse)
    [180, 215,  75],   # yellow-green     (recovering)
    [  0,  75,  15],   # dark forest-green (healthy)
], dtype=np.float32)


def _build_nbr_lut() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    ts = np.linspace(0.0, 1.0, 256)
    for i, t in enumerate(ts):
        idx = np.searchsorted(_NBR_STOPS_T, t, side="right") - 1
        idx = int(np.clip(idx, 0, len(_NBR_STOPS_T) - 2))
        t0, t1 = _NBR_STOPS_T[idx], _NBR_STOPS_T[idx + 1]
        alpha = (t - t0) / (t1 - t0 + 1e-9)
        rgb = _NBR_STOPS_RGB[idx] * (1 - alpha) + _NBR_STOPS_RGB[idx + 1] * alpha
        lut[i] = np.clip(rgb, 0, 255).astype(np.uint8)
    return lut


_NBR_LUT = _build_nbr_lut()


# --------------------------------------------------------------------------- #
# NDSI colormap: snow index (B03-B11)/(B03+B11)
# ndsi=-1.0 → t=0.00 → dark soil/rock  (no snow)
# ndsi= 0.0 → t=0.50 → warm tan        (bare ground)
# ndsi= 0.4 → t=0.70 → pale blue       (snow threshold)
# ndsi= 1.0 → t=1.00 → white/ice       (deep snow)
# --------------------------------------------------------------------------- #
_NDSI_STOPS_T = np.array([0.00, 0.50, 0.70, 1.00], dtype=np.float32)
_NDSI_STOPS_RGB = np.array([
    [100,  65,  25],   # dark soil/rock
    [205, 175, 110],   # warm tan
    [170, 215, 245],   # pale blue (snow threshold)
    [245, 252, 255],   # near-white ice
], dtype=np.float32)


def _build_ndsi_lut() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    ts = np.linspace(0.0, 1.0, 256)
    for i, t in enumerate(ts):
        idx = np.searchsorted(_NDSI_STOPS_T, t, side="right") - 1
        idx = int(np.clip(idx, 0, len(_NDSI_STOPS_T) - 2))
        t0, t1 = _NDSI_STOPS_T[idx], _NDSI_STOPS_T[idx + 1]
        alpha = (t - t0) / (t1 - t0 + 1e-9)
        rgb = _NDSI_STOPS_RGB[idx] * (1 - alpha) + _NDSI_STOPS_RGB[idx + 1] * alpha
        lut[i] = np.clip(rgb, 0, 255).astype(np.uint8)
    return lut


_NDSI_LUT = _build_ndsi_lut()


# --------------------------------------------------------------------------- #
# BSI colormap: bare soil index (B11+B04-B08-B02)/(B11+B04+B08+B02)
# bsi=-1.0 → t=0.00 → dark green       (dense vegetation)
# bsi=-0.1 → t=0.45 → yellow-green     (light vegetation)
# bsi= 0.0 → t=0.50 → pale             (boundary)
# bsi= 0.3 → t=0.65 → light tan        (partial exposure)
# bsi= 1.0 → t=1.00 → dark brown       (very bare)
# --------------------------------------------------------------------------- #
_BSI_STOPS_T = np.array([0.00, 0.45, 0.50, 0.65, 1.00], dtype=np.float32)
_BSI_STOPS_RGB = np.array([
    [  0,  80,  20],   # dark green     (dense vegetation)
    [155, 205,  80],   # yellow-green   (light vegetation)
    [235, 225, 185],   # pale           (boundary)
    [205, 165,  90],   # light tan      (partial exposure)
    [115,  65,  20],   # dark brown     (very bare)
], dtype=np.float32)


def _build_bsi_lut() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    ts = np.linspace(0.0, 1.0, 256)
    for i, t in enumerate(ts):
        idx = np.searchsorted(_BSI_STOPS_T, t, side="right") - 1
        idx = int(np.clip(idx, 0, len(_BSI_STOPS_T) - 2))
        t0, t1 = _BSI_STOPS_T[idx], _BSI_STOPS_T[idx + 1]
        alpha = (t - t0) / (t1 - t0 + 1e-9)
        rgb = _BSI_STOPS_RGB[idx] * (1 - alpha) + _BSI_STOPS_RGB[idx + 1] * alpha
        lut[i] = np.clip(rgb, 0, 255).astype(np.uint8)
    return lut


_BSI_LUT = _build_bsi_lut()


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


def _index_to_b64(arr: np.ndarray, lut: np.ndarray, scale: int = 4) -> str:
    """Generic helper: map a [-1, 1] float array through a 256-entry RGB LUT."""
    arr = np.nan_to_num(arr.astype(np.float32), nan=0.0)
    idx = np.clip(((arr + 1) / 2 * 255).astype(np.int32), 0, 255)
    rgb = lut[idx]
    img = Image.fromarray(rgb, mode="RGB")
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
    return _index_to_b64(ndvi, _NDVI_LUT, scale)


def ndmi_to_b64(nir: np.ndarray, swir: np.ndarray, scale: int = 4) -> str:
    """Compute NDMI=(NIR-SWIR)/(NIR+SWIR) and render with the NDMI colormap."""
    nir = nir.astype(np.float32)
    swir = swir.astype(np.float32)
    denom = nir + swir
    with np.errstate(invalid="ignore", divide="ignore"):
        ndmi = np.where(denom > 0, (nir - swir) / denom, np.nan)
    return _index_to_b64(ndmi, _NDMI_LUT, scale)


def nbr_to_b64(nir: np.ndarray, swir2: np.ndarray, scale: int = 4) -> str:
    """Compute NBR=(NIR-SWIR2)/(NIR+SWIR2) and render with the NBR colormap."""
    nir = nir.astype(np.float32)
    swir2 = swir2.astype(np.float32)
    denom = nir + swir2
    with np.errstate(invalid="ignore", divide="ignore"):
        nbr = np.where(denom > 0, (nir - swir2) / denom, np.nan)
    return _index_to_b64(nbr, _NBR_LUT, scale)


def ndsi_to_b64(green: np.ndarray, swir: np.ndarray, scale: int = 4) -> str:
    """Compute NDSI=(GREEN-SWIR)/(GREEN+SWIR) and render with the NDSI colormap."""
    green = green.astype(np.float32)
    swir = swir.astype(np.float32)
    denom = green + swir
    with np.errstate(invalid="ignore", divide="ignore"):
        ndsi = np.where(denom > 0, (green - swir) / denom, np.nan)
    return _index_to_b64(ndsi, _NDSI_LUT, scale)


def bsi_to_b64(
    swir: np.ndarray,
    red: np.ndarray,
    nir: np.ndarray,
    blue: np.ndarray,
    scale: int = 4,
) -> str:
    """Compute BSI=(SWIR+RED-NIR-BLUE)/(SWIR+RED+NIR+BLUE) and render with BSI colormap."""
    swir = swir.astype(np.float32)
    red = red.astype(np.float32)
    nir = nir.astype(np.float32)
    blue = blue.astype(np.float32)
    num = swir + red - nir - blue
    den = swir + red + nir + blue
    with np.errstate(invalid="ignore", divide="ignore"):
        bsi = np.where(den > 0, num / den, np.nan)
    return _index_to_b64(bsi, _BSI_LUT, scale)
