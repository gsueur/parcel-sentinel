from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import settings


@dataclass
class MaskStats:
    valid_pixel_count: int
    total_pixel_count: int
    cloud_fraction: float

    @property
    def valid_fraction(self) -> float:
        if self.total_pixel_count == 0:
            return 0.0
        return self.valid_pixel_count / self.total_pixel_count


def apply_scl_mask(
    scl: np.ndarray,
    valid_classes: list[int] | None = None,
) -> tuple[np.ndarray, MaskStats]:
    """Create a boolean mask from SCL band.

    Args:
        scl: Scene Classification Layer array.
        valid_classes: SCL class values considered clear/valid.

    Returns:
        (mask, stats) where mask is True for valid pixels.
    """
    if valid_classes is None:
        valid_classes = settings.SCL_VALID_CLASSES

    valid_mask = np.isin(scl, valid_classes)
    total = scl.size
    valid_count = int(valid_mask.sum())
    cloud_count = total - valid_count

    stats = MaskStats(
        valid_pixel_count=valid_count,
        total_pixel_count=total,
        cloud_fraction=cloud_count / total if total > 0 else 0.0,
    )

    return valid_mask, stats


def mask_band(band: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """Apply valid mask to a band, setting invalid pixels to NaN."""
    result = band.astype(np.float32).copy()
    result[~valid_mask] = np.nan
    return result
