"""Forecast error metrics. Architecture.md Section 6: "MAE / MAPE / RMSE on the held-out
test window, reported against two baselines... both baseline numbers get published
alongside the model's."
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastMetrics:
    mae: float
    mape: float
    rmse: float
    n: int  # rows actually scored, after dropping anything NaN on either side

    def __str__(self) -> str:
        return f"MAE={self.mae:.1f}  MAPE={self.mape:.2%}  RMSE={self.rmse:.1f}  (n={self.n})"


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
    mape = (err.abs() / aligned["actual"].abs()).mean()

    return ForecastMetrics(mae=float(mae), mape=float(mape), rmse=rmse, n=len(aligned))
