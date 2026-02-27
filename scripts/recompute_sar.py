#!/usr/bin/env python3
"""Force recompute SAR features and scores for all stored locations.

Uses already-stored sar_scene_bands data (water_frac + rel_orbit) -- no STAC
searches or COG reads required.  Run this after algorithm changes to SAR
water frequency or flood anomaly detection.

Usage (on the production server, service must be stopped first):
    cd /home/debian/REMOTESENSING/location-sentinel   # or /opt/location-sentinel
    sudo systemctl stop location-sentinel
    source .env && .venv/bin/python scripts/recompute_sar.py
    sudo systemctl start location-sentinel
"""
from __future__ import annotations

import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Imports -- path already set if run from the project root with the venv
# ---------------------------------------------------------------------------
from location_sentinel.config import settings
from location_sentinel.compute.sar_features import (
    compute_sar_flood_anomaly,
    compute_sar_water_frequency,
)
from location_sentinel.compute.scoring import compute_scores
from location_sentinel.storage.duckdb_store import store


def main() -> None:
    store.connect()
    conn = store._conn

    # Load all feature rows for the current processing version
    rows = conn.execute(
        """
        SELECT lf.location_key, lf.date_start, lf.date_end,
               lf.features_json, lf.quality_json,
               lg.climate_code
        FROM location_features lf
        LEFT JOIN location_geometries lg ON lf.location_key = lg.location_key
        WHERE lf.processing_version = ?
        ORDER BY lf.location_key
        """,
        [settings.PROCESSING_VERSION],
    ).fetchall()

    logger.info(
        "Processing version: %s  |  Score version: %s",
        settings.PROCESSING_VERSION,
        settings.SCORE_VERSION,
    )
    logger.info("Found %d location-version entries.", len(rows))

    updated = 0
    skipped = 0

    for location_key, date_start, date_end, features_json, quality_json, climate_code in rows:
        features: dict = json.loads(features_json)
        quality: dict = json.loads(quality_json)

        # ------------------------------------------------------------------
        # Load all SAR scenes for this location
        # ------------------------------------------------------------------
        sar_rows = conn.execute(
            """
            SELECT month_key, water_frac, rel_orbit
            FROM sar_scene_bands
            WHERE location_key = ? AND processing_version = ?
            ORDER BY month_key ASC
            """,
            [location_key, settings.PROCESSING_VERSION],
        ).fetchall()

        if not sar_rows:
            logger.info("  [skip] %s -- no SAR scenes stored", location_key)
            skipped += 1
            continue

        sar_scene_fracs: list[tuple[str, float, int]] = [
            (mk, float(wf), int(ro or 0))
            for mk, wf, ro in sar_rows
            if wf is not None
        ]

        if not sar_scene_fracs:
            logger.info("  [skip] %s -- all SAR scenes have null water_frac", location_key)
            skipped += 1
            continue

        # ------------------------------------------------------------------
        # Load NDSI timeseries for snow-month suppression
        # ------------------------------------------------------------------
        ndsi_row = conn.execute(
            """
            SELECT series_json FROM location_timeseries
            WHERE location_key = ? AND processing_version = ?
              AND metric = 'ndsi' AND cadence = 'monthly'
            """,
            [location_key, settings.PROCESSING_VERSION],
        ).fetchone()

        snow_months: set[str] = set()
        if ndsi_row:
            ndsi_series: list[dict] = json.loads(ndsi_row[0])
            snow_months = {
                rec["month"]
                for rec in ndsi_series
                if rec.get("mean") is not None
                and rec["mean"] > settings.NDSI_SNOW_THRESHOLD
            }

        # ------------------------------------------------------------------
        # Recompute sar_water_freq_5y  (orbit-stratified, MAD-based, snow-suppressed)
        # ------------------------------------------------------------------
        non_snow = [
            (wf, orbit)
            for mk, wf, orbit in sar_scene_fracs
            if mk not in snow_months
        ]
        new_water_freq = compute_sar_water_frequency(non_snow) if non_snow else None

        # ------------------------------------------------------------------
        # Recompute sar_flood_anomaly  (all scenes, no snow suppression)
        # ------------------------------------------------------------------
        new_flood_anomaly = compute_sar_flood_anomaly(
            [(mk, wf) for mk, wf, _ in sar_scene_fracs],
            date_end,
        )

        old_water_freq = features.get("sar_water_freq_5y")
        old_flood_anomaly = features.get("sar_flood_anomaly")

        # ------------------------------------------------------------------
        # Patch features dict
        # ------------------------------------------------------------------
        quality_flags: list[str] = quality.get("flags", [])

        if new_water_freq is not None:
            features["sar_water_freq_5y"] = new_water_freq
            quality["flags"] = [f for f in quality_flags if f != "no_sar_data"]
        else:
            features["sar_water_freq_5y"] = None
            if "no_sar_data" not in quality_flags:
                quality.setdefault("flags", []).append("no_sar_data")

        if new_flood_anomaly is not None:
            features["sar_flood_anomaly"] = new_flood_anomaly
        else:
            features.pop("sar_flood_anomaly", None)

        logger.info(
            "  %s | water_freq %s→%s | flood_anomaly %s→%s | snow_months=%d",
            location_key,
            f"{old_water_freq:.4f}" if old_water_freq is not None else "None",
            f"{new_water_freq:.4f}" if new_water_freq is not None else "None",
            f"{old_flood_anomaly:.4f}" if old_flood_anomaly is not None else "None",
            f"{new_flood_anomaly:.4f}" if new_flood_anomaly is not None else "None",
            len(snow_months),
        )

        # ------------------------------------------------------------------
        # Save features
        # ------------------------------------------------------------------
        store.save_features(
            location_key,
            settings.PROCESSING_VERSION,
            date_start,
            date_end,
            features,
            quality,
        )

        # ------------------------------------------------------------------
        # Recompute and save scores
        # ------------------------------------------------------------------
        result = compute_scores(features, climate_code)
        store.save_scores(
            location_key,
            settings.SCORE_VERSION,
            5,
            {
                "drought_score": result.drought_score,
                "wetness_score": result.wetness_score,
                "fire_exposure_score": result.fire_exposure_score,
                "heat_mitigation_score": result.heat_mitigation_score,
                "flood_risk_score": result.flood_risk_score,
                "heat_stress_score": result.heat_stress_score,
                "composite_score": result.composite_score,
                "top_factors": result.top_factors,
                "climate_profile": result.climate_profile,
            },
        )

        updated += 1

    logger.info(
        "Done. Updated=%d  Skipped=%d  Total=%d",
        updated, skipped, len(rows),
    )
    store.close()


if __name__ == "__main__":
    main()
