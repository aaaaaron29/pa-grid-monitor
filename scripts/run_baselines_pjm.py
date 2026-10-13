#!/usr/bin/env python
"""PJM (private tier) equivalent of scripts/run_baselines.py -- same methodology, applied
with its own reasoning rather than copy-pasting the EIA script's assumptions.

Differences from the EIA version, each deliberate:
  - 5-minute grain, not hourly: "same hour, previous week" becomes "same 5-min slot,
    previous week" -> lag_periods=2016 (7 days * 288 periods/day), not the EIA default of 168.
  - No plausibility masking: real PJM prices are legitimately extreme (Architecture.md
    Section 6) -- the EIA-specific sentinel-value fix does not apply here.
  - PJM's own split dates (model/splits.py PJM_*), proportioned to the ~169 days of real
    history actually available, not EIA's multi-year absolute dates.
  - Runs once per zone -- there is no single "PJM demand", each zone is its own series.

Usage: python scripts/run_baselines_pjm.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from model import splits  # noqa: E402
from model.baselines import DowHourProfile, seasonal_naive_predict  # noqa: E402
from model.data import apply_missing_data_policy  # noqa: E402
from model.data_pjm import ZONES, load_pjm_series  # noqa: E402
from model.evaluate import evaluate  # noqa: E402

log = logging.getLogger("run_baselines_pjm")

# 7 days * 24 hours * 12 (five-minute periods/hour) -- "same slot, previous week" at this feed's
# actual granularity, not hourly data's 168.
SEASONAL_NAIVE_LAG_PERIODS = 7 * 24 * 12

# PJM backfill data is confirmed gap-free (Architecture.md Section 6 / model/data_pjm.py
# docstring); this only matters if the live poller later contributes a genuinely missing
# interval. 3 periods = 15 minutes, a conservative short-gap allowance for 5-min data.
MAX_FORWARD_FILL_PERIODS = 3


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    print("\n=== PJM baseline forecast metrics (validation window, per zone) ===\n")

    for zone in ZONES:
        log.info("loading PJM LMP series", extra={"zone": zone})
        raw = load_pjm_series(
            settings.postgres_dsn, zone, splits.PJM_TRAIN_START, splits.PJM_FREEZE_DATE
        )
        values, quality = apply_missing_data_policy(
            raw, max_forward_fill_periods=MAX_FORWARD_FILL_PERIODS
        )

        train_mask = splits.split_mask(values.index, splits.PJM_TRAIN_START, splits.PJM_TRAIN_END)
        val_mask = splits.split_mask(
            values.index, splits.PJM_VALIDATION_START, splits.PJM_VALIDATION_END
        )

        train_series = values[train_mask & (quality != "excluded")]
        val_series = values[val_mask & (quality != "excluded")]
        full_series = values[quality != "excluded"]

        naive_pred = seasonal_naive_predict(
            full_series, lag_periods=SEASONAL_NAIVE_LAG_PERIODS
        ).reindex(val_series.index)
        profile = DowHourProfile().fit(train_series)
        profile_pred = profile.predict(val_series.index)

        naive_metrics = evaluate(val_series, naive_pred)
        profile_metrics = evaluate(val_series, profile_pred)

        print(f"{zone}:")
        print(f"  seasonal-naive (same slot, previous week): {naive_metrics}")
        print(f"  dow x hour profile:                        {profile_metrics}")
        print()


if __name__ == "__main__":
    main()
