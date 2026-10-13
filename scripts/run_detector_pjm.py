#!/usr/bin/env python
"""PJM (private tier) equivalent of scripts/run_detector.py, run across all 5 PA zones.

Same detector/synthetic-injection code as the EIA path (model/detector.py,
model/synthetic_injection.py, model/flatline_detector.py are grain- and tier-agnostic) with
PJM-appropriate parameters: 5-minute grain, no plausibility masking (Architecture.md
Section 6: real PJM price extremes are signal, not sensor error), PJM's own split dates.

Usage: python scripts/run_detector_pjm.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from model import splits  # noqa: E402
from model.baselines import seasonal_naive_predict  # noqa: E402
from model.data import apply_missing_data_policy  # noqa: E402
from model.data_pjm import ZONES, load_pjm_series  # noqa: E402
from model.detector import Detector  # noqa: E402
from model.features import build_features  # noqa: E402
from model.flatline_detector import calibrate_floor, detect_flatline  # noqa: E402
from model.synthetic_injection import Injection, inject_many, recall_at_budget  # noqa: E402

log = logging.getLogger("run_detector_pjm")

ALERT_BUDGET = 0.01
SEASONAL_NAIVE_LAG_PERIODS = 7 * 24 * 12  # same slot, previous week, at 5-min grain
MAX_FORWARD_FILL_PERIODS = 3  # 15 minutes; see scripts/run_baselines_pjm.py
# 1-hour rolling window (12 * 5min) -- the EIA detector used 4 HOURS at hourly grain for the
# same reason (catch a multi-period pattern a single row can't show); 1 hour at 5-min grain
# is the directly analogous window, not a guess.
ROLLING_WINDOW_PERIODS = 12
# Matches the rolling window itself, same reasoning as scripts/run_detector.py.
FLATLINE_MIN_CONSECUTIVE_PERIODS = ROLLING_WINDOW_PERIODS

# Magnitudes checked against PECO's real validation residual distribution before picking
# these (Architecture.md's own "verify, don't assume"); a first, std-scaled pass at these
# numbers scored 0% recall on step_change and abnormal_ramp purely from being too small
# relative to the real residual tail (-628 to +2,661 $/MWh) -- the exact EIA-side lesson
# repeating. Retrying at ~3x magnitude raised them to meaningful levels. Reused as-is across
# all five zones rather than re-tuned per zone -- the zones share the same underlying market
# and broadly similar volatility, and re-calibrating five separate magnitude sets would
# trade a small amount of per-zone precision for a lot of extra complexity.
INJECTION_SPECS = {
    "spike (+1,500 $/MWh)": Injection("spike", {"at": 500, "magnitude": 1500.0}),
    "spike (-500 $/MWh)": Injection("spike", {"at": 2000, "magnitude": -500.0}),
    "step_change": Injection("step_change", {"start": 1000, "duration": 24, "magnitude": 1000.0}),
    "flatline": Injection("flatline", {"start": 2500, "duration": 96}),
    "abnormal_ramp": Injection(
        "abnormal_ramp", {"start": 4000, "duration": 36, "total_magnitude": 3000.0}
    ),
}


def run_for_zone(settings, zone: str) -> None:
    log.info("loading PJM LMP series", extra={"zone": zone})
    raw = load_pjm_series(
        settings.postgres_dsn, zone, splits.PJM_TRAIN_START, splits.PJM_FREEZE_DATE
    )
    values, quality = apply_missing_data_policy(
        raw, max_forward_fill_periods=MAX_FORWARD_FILL_PERIODS
    )
    usable = values[quality != "excluded"]
    forecast = seasonal_naive_predict(usable, lag_periods=SEASONAL_NAIVE_LAG_PERIODS)

    train_mask = splits.split_mask(usable.index, splits.PJM_TRAIN_START, splits.PJM_TRAIN_END)
    val_mask = splits.split_mask(
        usable.index, splits.PJM_VALIDATION_START, splits.PJM_VALIDATION_END
    )

    train_features = build_features(
        usable[train_mask], forecast[train_mask], rolling_window_periods=ROLLING_WINDOW_PERIODS
    )
    val_actual = usable[val_mask]
    val_forecast = forecast[val_mask]
    val_features = build_features(
        val_actual, val_forecast, rolling_window_periods=ROLLING_WINDOW_PERIODS
    )

    n = len(val_actual)
    starts = [i.kwargs.get("start", i.kwargs.get("at", 0)) for i in INJECTION_SPECS.values()]
    max_duration = max(i.kwargs.get("duration", 0) for i in INJECTION_SPECS.values())
    if max(starts) + max_duration >= n:
        raise RuntimeError(
            f"{zone}: validation window ({n} rows) too short for the configured injections"
        )

    detector = Detector().fit(train_features)
    clean_val_scores = detector.score(val_features)
    detector.calibrate_threshold(clean_val_scores, alert_budget=ALERT_BUDGET)

    flatline_floor = calibrate_floor(train_features["rolling_std"])
    clean_flatline_flags = detect_flatline(
        val_features["rolling_std"], flatline_floor, FLATLINE_MIN_CONSECUTIVE_PERIODS
    )
    clean_flatline_rate = clean_flatline_flags.sum() / clean_flatline_flags.notna().sum()

    print(f"\n{zone} (flatline rule clean fire rate: {clean_flatline_rate:.2%}):")

    for name, injection in INJECTION_SPECS.items():
        perturbed_actual, mask = inject_many(val_actual, [injection])
        perturbed_features = build_features(
            perturbed_actual, val_forecast, rolling_window_periods=ROLLING_WINDOW_PERIODS
        )
        scores = detector.score(perturbed_features)
        ml_flags = detector.flag(scores)
        rule_flags = detect_flatline(
            perturbed_features["rolling_std"], flatline_floor, FLATLINE_MIN_CONSECUTIVE_PERIODS
        )
        combined_flags = ml_flags | rule_flags
        ml_recall = recall_at_budget(mask, ml_flags)
        combined_recall = recall_at_budget(mask, combined_flags)
        print(
            f"  {name:<22s} forest={ml_recall:>6.1%}   combined={combined_recall:>6.1%}"
            f"   injected={int(mask.sum())}"
        )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    print("=== PJM synthetic-injection evaluation, all 5 PA zones (validation window) ===")
    print(f"alert budget: {ALERT_BUDGET:.1%}")

    for zone in ZONES:
        run_for_zone(settings, zone)

    print()


if __name__ == "__main__":
    main()
