#!/usr/bin/env python
"""Fits the isolation forest on train, calibrates its threshold on validation, then runs
the synthetic-injection harness -- the only quantitative handle on detector quality
(Architecture.md Section 6: no real anomaly labels exist for this data).

Usage: python scripts/run_detector.py
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
from model.data import apply_missing_data_policy, load_eia_series  # noqa: E402
from model.detector import Detector  # noqa: E402
from model.features import build_features  # noqa: E402
from model.flatline_detector import calibrate_floor, detect_flatline  # noqa: E402
from model.synthetic_injection import Injection, inject_many, recall_at_budget  # noqa: E402

log = logging.getLogger("run_detector")

ALERT_BUDGET = 0.01  # Architecture.md Section 6: "at most 1% of intervals flagged"
# Matches the 4-period rolling_std window itself -- a genuinely stuck sensor should be quiet
# for at least as long as the window that's supposed to notice it, not just one lucky period.
FLATLINE_MIN_CONSECUTIVE_PERIODS = 4


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    log.info("loading EIA demand series from Postgres")
    raw = load_eia_series(
        settings.postgres_dsn, start=splits.EIA_TRAIN_START, end=splits.EIA_FREEZE_DATE
    )
    values, quality = apply_missing_data_policy(raw)
    usable = values[quality != "excluded"]

    # Seasonal-naive residuals are what gets scored (Architecture.md Section 6: "the
    # isolation forest's residuals should be scored against seasonal-naive specifically").
    # Needs the full index (not just one split's slice) so the 168h lag has history to draw
    # on right at a split boundary, same reasoning as scripts/run_baselines.py.
    forecast = seasonal_naive_predict(usable)

    train_mask = splits.split_mask(usable.index, splits.EIA_TRAIN_START, splits.EIA_TRAIN_END)
    val_mask = splits.split_mask(
        usable.index, splits.EIA_VALIDATION_START, splits.EIA_VALIDATION_END
    )

    train_features = build_features(usable[train_mask], forecast[train_mask])
    val_actual = usable[val_mask]
    val_forecast = forecast[val_mask]
    val_features = build_features(val_actual, val_forecast)

    log.info(
        "fitting detector",
        extra={"train_rows": len(train_features), "validation_rows": len(val_features)},
    )
    detector = Detector().fit(train_features)

    clean_val_scores = detector.score(val_features)
    threshold = detector.calibrate_threshold(clean_val_scores, alert_budget=ALERT_BUDGET)
    log.info("threshold calibrated on clean validation", extra={"threshold": threshold})

    # Rule-based flatline check, running ALONGSIDE the isolation forest rather than as one
    # more diluted input feature (Architecture.md Section 6: confirmed live, twice, that the
    # forest structurally can't see a stuck sensor no matter how long it runs). Floor fit on
    # TRAIN only, same rule as the forest itself.
    flatline_floor = calibrate_floor(train_features["rolling_std"])
    clean_flatline_flags = detect_flatline(
        val_features["rolling_std"], flatline_floor, FLATLINE_MIN_CONSECUTIVE_PERIODS
    )
    clean_flatline_rate = clean_flatline_flags.sum() / clean_flatline_flags.notna().sum()
    log.info(
        "flatline rule calibrated on train",
        extra={"floor": flatline_floor, "clean_validation_fire_rate": clean_flatline_rate},
    )

    # Spread four injection types across non-overlapping windows of the validation actual
    # series. Simplification worth stating plainly: because the forecast is seasonal-naive
    # (168h lag), an injected value can itself become a future forecast input 7 days later --
    # windows below are spaced well apart and the harness reports recall on the injected
    # positions only, not a claim that no other scored point was ever indirectly touched.
    n = len(val_actual)
    named_injections = {
        "spike (+40,000)": Injection("spike", {"at": 200, "magnitude": 40_000.0}),
        "spike (-35,000)": Injection("spike", {"at": 1800, "magnitude": -35_000.0}),
        "step_change": Injection(
            "step_change", {"start": 600, "duration": 12, "magnitude": 25_000.0}
        ),
        "flatline": Injection("flatline", {"start": 1200, "duration": 8}),
        "abnormal_ramp": Injection(
            "abnormal_ramp", {"start": 3000, "duration": 10, "total_magnitude": 30_000.0}
        ),
    }
    starts = [i.kwargs.get("start", i.kwargs.get("at", 0)) for i in named_injections.values()]
    if max(starts) >= n:
        raise RuntimeError(
            f"validation window ({n} rows) too short for the configured injection positions"
        )

    print("\n=== Synthetic-injection evaluation (validation window) ===")
    print(f"alert budget: {ALERT_BUDGET:.1%}  |  flatline rule clean fire rate: "
          f"{clean_flatline_rate:.2%}\n")
    print("Per-type recall: isolation forest alone, then forest OR flatline rule combined")
    print("(reported individually, not blended into one number, because sensitivity turned")
    print("out to be strongly type-dependent -- see Architecture.md Section 6 for why):\n")

    for name, injection in named_injections.items():
        perturbed_actual, mask = inject_many(val_actual, [injection])
        perturbed_features = build_features(perturbed_actual, val_forecast)
        scores = detector.score(perturbed_features)
        ml_flags = detector.flag(scores)
        rule_flags = detect_flatline(
            perturbed_features["rolling_std"], flatline_floor, FLATLINE_MIN_CONSECUTIVE_PERIODS
        )
        combined_flags = ml_flags | rule_flags
        ml_recall = recall_at_budget(mask, ml_flags)
        combined_recall = recall_at_budget(mask, combined_flags)
        print(
            f"  {name:<20s} forest={ml_recall:>6.1%}   combined={combined_recall:>6.1%}"
            f"   injected={int(mask.sum())}"
        )

    # Aggregate: all five injected together, same run a dashboard-style single number would
    # show -- included for completeness, but the per-type breakdown above is the real result.
    perturbed_actual, injected_mask = inject_many(val_actual, list(named_injections.values()))
    perturbed_features = build_features(perturbed_actual, val_forecast)
    perturbed_scores = detector.score(perturbed_features)
    ml_flags = detector.flag(perturbed_scores)
    rule_flags = detect_flatline(
        perturbed_features["rolling_std"], flatline_floor, FLATLINE_MIN_CONSECUTIVE_PERIODS
    )
    combined_flags = ml_flags | rule_flags
    aggregate_ml_recall = recall_at_budget(injected_mask, ml_flags)
    aggregate_combined_recall = recall_at_budget(injected_mask, combined_flags)
    flagged_fraction = combined_flags.sum() / combined_flags.notna().sum()

    print(
        f"\n  {'aggregate (all types)':<20s} forest={aggregate_ml_recall:>6.1%}"
        f"   combined={aggregate_combined_recall:>6.1%}   injected={int(injected_mask.sum())}"
    )
    print(f"\nactual flagged fraction on this run (combined): {flagged_fraction:.2%}")
    print()


if __name__ == "__main__":
    main()
