"""Forecast error metrics. Architecture.md Section 6: "MAE / MAPE / RMSE on the held-out
test window, reported against two baselines... both baseline numbers get published
alongside the model's."

MAPE is unreliable whenever the actual series comes anywhere near zero -- its denominator
is |actual|, so a single zero makes it literally undefined (division by zero -> inf), and
values merely close to zero can dominate the mean even without an exact zero. This is fine
for EIA demand (always comfortably positive, hundreds of MW at minimum) and NOT fine for PJM
LMP (confirmed live, 2026-10-13: real zone prices cross zero routinely -- negative prices are
a genuine, common market phenomenon, not an edge case). Rather than silently print a
meaningless "inf%", MAPE is reported as None when non-finite; callers scoring price-like
series should treat MAE/RMSE as the metrics that actually matter and MAPE as EIA-tier-only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastMetrics:
    mae: float
    mape: float | None  # None when actual crosses/sits at zero -- see module docstring
    rmse: float
    n: int  # rows actually scored, after dropping anything NaN on either side

    def __str__(self) -> str:
        mape_str = f"{self.mape:.2%}" if self.mape is not None else "n/a (actual crosses zero)"
        return f"MAE={self.mae:.1f}  MAPE={mape_str}  RMSE={self.rmse:.1f}  (n={self.n})"


def evaluate(actual: pd.Series, predicted: pd.Series) -> ForecastMetrics:
    """Both series must share an index; rows where either side is NaN (an excluded gap in
    `actual`, or a cold-start/unseen-bucket NaN in `predicted`) are dropped before scoring,
    never imputed — a baseline shouldn't get credit or blame for a row nobody could predict."""
    aligned = pd.DataFrame({"actual": actual, "predicted": predicted}).dropna()
    if aligned.empty:
        raise ValueError("no overlapping, non-NaN rows between actual and predicted")

    err = aligned["predicted"] - aligned["actual"]
    mae = err.abs().mean()
    rmse = float(np.sqrt((err**2).mean()))
    raw_mape = (err.abs() / aligned["actual"].abs()).mean()
    mape = float(raw_mape) if math.isfinite(raw_mape) else None

    return ForecastMetrics(mae=float(mae), mape=mape, rmse=rmse, n=len(aligned))
