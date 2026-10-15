#!/usr/bin/env python
"""Out-of-sample flag rate of the PJM detector, per zone, with event counts.

scripts/run_detector_pjm.py reports recall on synthetic injections in the VALIDATION window.
It never reports how often the detector actually flags on data it was not calibrated on,
which is the number the alert budget is about. This does, read-only (it trains in memory and
writes nothing):

  val   the window the threshold was calibrated on (about 1% by construction)
  test  the frozen test window
  post  everything after the freeze date, up to now

It also counts distinct EVENTS (flagged intervals less than an hour apart are one event),
because price spikes cluster and an interval rate overstates how often anything happens.
A "spike" flag is one on an interval whose price is itself beyond +/-$300/MWh. An "echo" flag
is one on a calm interval where the price a week earlier was a spike, which the one-week
seasonal-naive baseline replays as an expected spike.

The same table is produced for a spike-robust baseline (median of the last three weeks) so
the choice not to adopt it stays checkable.

Usage: python scripts/evaluate_flag_rate_pjm.py
"""
from __future__ import annotations

import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from model import splits  # noqa: E402
from model.baselines import seasonal_naive_predict  # noqa: E402
from model.data import apply_missing_data_policy  # noqa: E402
from model.data_pjm import ZONES, load_pjm_series  # noqa: E402
from model.detector import Detector  # noqa: E402
from model.features import build_features  # noqa: E402

ALERT_BUDGET = 0.01
WEEK = 7 * 24 * 12  # same slot, previous week, at 5-minute grain
ROLLING_WINDOW_PERIODS = 12
EVENT_GAP_PERIODS = 12  # flags within an hour of each other are one event
SPIKE_ABS_PRICE = 300.0
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


def robust_weekly(series: pd.Series, weeks: int = 3, min_count: int = 2) -> pd.Series:
    lags = pd.concat([series.shift(WEEK * k) for k in range(1, weeks + 1)], axis=1)
    median = lags.median(axis=1, skipna=True)
    median[lags.notna().sum(axis=1) < min_count] = np.nan
    return median


def count_events(flag: pd.Series) -> int:
    idx = np.flatnonzero(flag.values)
    if len(idx) == 0:
        return 0
    return int(1 + (np.diff(idx) > EVENT_GAP_PERIODS).sum())


def evaluate(zone: str, name: str, make_forecast, now: datetime) -> dict:
    raw = load_pjm_series(get_settings().postgres_dsn, zone, splits.PJM_TRAIN_START, now)
    values, quality = apply_missing_data_policy(raw, max_forward_fill_periods=3)
    usable = values[quality != "excluded"]
    forecast = make_forecast(usable)

    def window(start, end):
        return splits.split_mask(usable.index, start, end)

    def features(mask):
        return build_features(
            usable[mask],
            forecast[mask],
            rate_of_change_lag_periods=1,
            rolling_window_periods=ROLLING_WINDOW_PERIODS,
        )

    train = window(splits.PJM_TRAIN_START, splits.PJM_TRAIN_END)
    val = window(splits.PJM_VALIDATION_START, splits.PJM_VALIDATION_END)
    test = window(splits.PJM_TEST_START, splits.PJM_FREEZE_DATE)
    post = window(splits.PJM_FREEZE_DATE, FAR_FUTURE)

    detector = Detector().fit(features(train))
    detector.calibrate_threshold(detector.score(features(val)), alert_budget=ALERT_BUDGET)

    row: dict = {"zone": zone, "baseline": name}
    for label, mask in (("val", val), ("test", test), ("post", post)):
        feats = features(mask)
        scores = detector.score(feats)
        flag = detector.flag(scores).fillna(False)
        row[f"{label}_pct"] = round(100 * flag[scores.notna()].mean(), 2)
        row[f"{label}_events"] = count_events(flag)
        if label == "post":
            price = usable[mask].reindex(feats.index)
            last_week = usable.shift(WEEK).reindex(feats.index)
            calm = price.abs() <= SPIKE_ABS_PRICE
            row["post_flags"] = int(flag.sum())
            row["post_spike"] = int((flag & ~calm).sum())
            row["post_echo"] = int((flag & calm & (last_week.abs() > SPIKE_ABS_PRICE)).sum())
    return row


def main() -> None:
    warnings.filterwarnings("ignore")
    now = datetime.now(UTC)
    baselines = {
        "one-week lag (production)": lambda s: seasonal_naive_predict(s, lag_periods=WEEK),
        "median of 3 weeks": robust_weekly,
    }
    rows = [evaluate(z, name, fn, now) for z in ZONES for name, fn in baselines.items()]
    table = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(f"alert budget {ALERT_BUDGET:.0%}; test window ends {splits.PJM_FREEZE_DATE:%Y-%m-%d}\n")
    print(table.to_string(index=False))
    print("\nAcross zones:")
    summary = table.groupby("baseline").agg(
        val_pct=("val_pct", "mean"),
        test_pct=("test_pct", "mean"),
        post_pct=("post_pct", "mean"),
        test_events=("test_events", "sum"),
        post_events=("post_events", "sum"),
        post_flags=("post_flags", "sum"),
        post_spike=("post_spike", "sum"),
        post_echo=("post_echo", "sum"),
    )
    print(summary.round(2).to_string())


if __name__ == "__main__":
    main()
