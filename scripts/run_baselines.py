#!/usr/bin/env python
"""Fits both forecast baselines on train, evaluates on validation. Architecture.md Section 9
Phase 2: "baselines first... Both baseline numbers get published alongside the model's."

This is the first real output of Phase 2 — prints the numbers any future model (isolation
forest on residuals, optionally an LSTM) has to beat to justify shipping.

Usage: python scripts/run_baselines.py
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
from model.data import apply_missing_data_policy, load_eia_series  # noqa: E402
from model.evaluate import evaluate  # noqa: E402

log = logging.getLogger("run_baselines")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    log.info("loading EIA demand series from Postgres")
    raw = load_eia_series(
        settings.postgres_dsn, start=splits.EIA_TRAIN_START, end=splits.EIA_FREEZE_DATE
    )
    values, quality = apply_missing_data_policy(raw)

    gap_counts = quality.value_counts()
    log.info("gap summary", extra={k: int(v) for k, v in gap_counts.items()})

    train_mask = splits.split_mask(values.index, splits.EIA_TRAIN_START, splits.EIA_TRAIN_END)
    val_mask = splits.split_mask(
        values.index, splits.EIA_VALIDATION_START, splits.EIA_VALIDATION_END
    )

    # Excluded-gap hours never participate in fitting or scoring, in either window.
    train_series = values[train_mask & (quality != "excluded")]
    val_series = values[val_mask & (quality != "excluded")]

    log.info(
        "split sizes",
        extra={"train_hours": len(train_series), "validation_hours": len(val_series)},
    )

    # Seasonal-naive needs lagged history, so give it the full (train+val) index and score
    # only the validation slice — using just val_series would make most of the window
    # unpredictable (no prior week inside a 6-month slice for its first 7 days).
    full_series = values[(quality != "excluded")]
    naive_pred = seasonal_naive_predict(full_series).reindex(val_series.index)

    profile = DowHourProfile().fit(train_series)
    profile_pred = profile.predict(val_series.index)

    naive_metrics = evaluate(val_series, naive_pred)
    profile_metrics = evaluate(val_series, profile_pred)

    print("\n=== Baseline forecast metrics (validation window) ===")
    print(f"seasonal-naive (same hour, previous week): {naive_metrics}")
    print(f"day-of-week x hour-of-day profile:          {profile_metrics}")
    print()


if __name__ == "__main__":
    main()
