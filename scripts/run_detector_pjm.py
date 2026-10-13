#!/usr/bin/env python
"""PJM (private tier) equivalent of scripts/run_detector.py, scoped to one zone (PECO).

Same detector/synthetic-injection code as the EIA path (model/detector.py,
model/synthetic_injection.py are grain- and tier-agnostic) with PJM-appropriate parameters:
5-minute grain, no plausibility masking (Architecture.md Section 6: real PJM price extremes
are signal, not sensor error), PJM's own split dates. Scoped to one zone deliberately -- the
pipeline is proven by the EIA run and this PJM run; extending to the other four zones is
mechanical repetition of the same proven code, not new engineering, and is left as a
straightforward follow-up rather than bloating this script into a 5-zone loop before anyone
has looked at whether PECO's result is even worth repeating five times over.

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
from model.data_pjm import load_pjm_series  # noqa: E402
from model.detector import Detector  # noqa: E402
from model.features import build_features  # noqa: E402
from model.synthetic_injection import Injection, inject_many, recall_at_budget  # noqa: E402

log = logging.getLogger("run_detector_pjm")

ZONE = "PECO"
ALERT_BUDGET = 0.01
SEASONAL_NAIVE_LAG_PERIODS = 7 * 24 * 12  # same slot, previous week, at 5-min grain
MAX_FORWARD_FILL_PERIODS = 3  # 15 minutes; see scripts/run_baselines_pjm.py
# 1-hour rolling window (12 * 5min) -- the EIA detector used 4 HOURS at hourly grain for the
# same reason (catch a multi-period pattern a single row can't show); 1 hour at 5-min grain
# is the directly analogous window, not a guess.
ROLLING_WINDOW_PERIODS = 12


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    log.info("loading PJM LMP series", extra={"zone": ZONE})
    raw = load_pjm_series(
        settings.postgres_dsn, ZONE, splits.PJM_TRAIN_START, splits.PJM_FREEZE_DATE
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

    log.info(
        "fitting detector",
        extra={
            "zone": ZONE,
            "train_rows": len(train_features),
            "validation_rows": len(val_features),
        },
    )
    detector = Detector().fit(train_features)
    clean_val_scores = detector.score(val_features)
    threshold = detector.calibrate_threshold(clean_val_scores, alert_budget=ALERT_BUDGET)
    log.info("threshold calibrated on clean validation", extra={"threshold": threshold})

    # Magnitudes checked against the real validation residual distribution before picking
    # these, not guessed (Architecture.md's own "verify, don't assume"). A first pass at
    # these numbers (300/-150/80/200-ish) turned out still too conservative -- step_change
    # and abnormal_ramp both scored 0% recall purely from being too small relative to the
    # real residual tail (-628 to +2,661), the exact EIA-side lesson repeating; confirmed by
    # retrying at ~3x magnitude, which raised them to 45.8% and 83.3%. These are that
    # confirmed-meaningful tier.
    n = len(val_actual)
    named_injections = {
        "spike (+1,500 $/MWh)": Injection("spike", {"at": 500, "magnitude": 1500.0}),
        "spike (-500 $/MWh)": Injection("spike", {"at": 2000, "magnitude": -500.0}),
        "step_change": Injection(
            "step_change", {"start": 1000, "duration": 24, "magnitude": 1000.0}
        ),
        "flatline": Injection("flatline", {"start": 2500, "duration": 96}),
        "abnormal_ramp": Injection(
            "abnormal_ramp", {"start": 4000, "duration": 36, "total_magnitude": 3000.0}
        ),
    }
    starts = [i.kwargs.get("start", i.kwargs.get("at", 0)) for i in named_injections.values()]
    max_duration = max(i.kwargs.get("duration", 0) for i in named_injections.values())
    if max(starts) + max_duration >= n:
        raise RuntimeError(
            f"validation window ({n} rows) too short for the configured injection positions"
        )

    print(f"\n=== PJM ({ZONE}) synthetic-injection evaluation (validation window) ===")
    print(f"alert budget: {ALERT_BUDGET:.1%}\n")

    for name, injection in named_injections.items():
        perturbed_actual, mask = inject_many(val_actual, [injection])
        perturbed_features = build_features(
            perturbed_actual, val_forecast, rolling_window_periods=ROLLING_WINDOW_PERIODS
        )
        scores = detector.score(perturbed_features)
        flags = detector.flag(scores)
        recall = recall_at_budget(mask, flags)
        print(f"  {name:<22s} recall={recall:>6.1%}   injected={int(mask.sum())}")

    perturbed_actual, injected_mask = inject_many(val_actual, list(named_injections.values()))
    perturbed_features = build_features(
        perturbed_actual, val_forecast, rolling_window_periods=ROLLING_WINDOW_PERIODS
    )
    perturbed_scores = detector.score(perturbed_features)
    flags = detector.flag(perturbed_scores)
    aggregate_recall = recall_at_budget(injected_mask, flags)
    flagged_fraction = flags.sum() / flags.notna().sum()

    print(f"\n  {'aggregate (all types)':<22s} recall={aggregate_recall:>6.1%}"
          f"   injected={int(injected_mask.sum())}")
    print(f"\nactual flagged fraction: {flagged_fraction:.2%} (budget target: {ALERT_BUDGET:.1%})")
    print()


if __name__ == "__main__":
    main()
