from __future__ import annotations

import struct
import zlib

import numpy as np


def _make_terrain_lut() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.float64)
    lut[0:31]    = np.linspace([34, 100, 34],   [80, 140, 60],   31)   # deep green
    lut[31:101]  = np.linspace([80, 140, 60],   [200, 180, 110], 70)   # green → tan
    lut[101:181] = np.linspace([200, 180, 110], [160, 120, 80],  80)   # tan → brown
    lut[181:231] = np.linspace([160, 120, 80],  [180, 180, 180], 50)   # brown → grey
    lut[231:256] = np.linspace([180, 180, 180], [255, 255, 255], 25)   # grey → white
    return lut.astype(np.uint8)


_TERRAIN_LUT = _make_terrain_lut()


def _encode_png(rgb: np.ndarray) -> bytes:
    """Minimal PNG encoder using stdlib zlib. rgb must be H×W×3 uint8."""
    h, w = rgb.shape[:2]

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def render_dem_png(elevation_bytes: bytes, elev_min: float, elev_max: float) -> bytes:
    """Render a hillshaded terrain PNG from raw 64×64 float32 elevation bytes.

    Returns a 64×64 PNG — native resolution, no upscaling.
    Uses NW sun (azimuth 315°, altitude 45°). Pure numpy + stdlib zlib.
    """
    data = np.frombuffer(elevation_bytes, dtype=np.float32).reshape(64, 64).astype(np.float64)

    # Hillshade (NW sun, 45° altitude) — pixel spacing ≈ 10 m after footprint fix
    dz_dy, dz_dx = np.gradient(data)
    slope = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
    aspect = (np.arctan2(-dz_dx, dz_dy) + 2 * np.pi) % (2 * np.pi)
    sun_az, sun_alt = np.radians(315), np.radians(45)
    hs = (
        np.cos(sun_alt) * np.cos(slope)
        + np.sin(sun_alt) * np.sin(slope) * np.cos(sun_az - aspect)
    )
    hs = np.clip((hs + 0.3) / 1.3, 0.0, 1.0)

    # Colormap via LUT
    rng = max(float(elev_max - elev_min), 1.0)
    norm = np.clip((data - elev_min) / rng, 0.0, 1.0)
    rgb = _TERRAIN_LUT[(norm * 255).astype(np.uint8)]  # 64×64×3 uint8

    blended = np.clip(rgb * hs[..., np.newaxis], 0, 255).astype(np.uint8)
    return _encode_png(blended)
