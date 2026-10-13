"""Synthetic anomaly injection harness -- the only quantitative handle on the detector,
since there are no real ground-truth anomaly labels (Architecture.md Section 6,
"Evaluating an unsupervised detector"):

    Inject labeled perturbations into held-out data at known timestamps: step changes,
    spikes, flatlines (stuck-sensor), and abnormal ramps, then report recall at a fixed
    alert budget (at most 1% of intervals flagged).

Each injector is a pure function: takes a clean series plus where/how big, returns
(perturbed_series, injected_mask). Composable -- inject_many layers several at
non-overlapping positions and returns the union mask, so one run can test all four types
at once against a single recall number, matching how the harness actually gets used.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def inject_spike(series: pd.Series, at: int, magnitude: float) -> tuple[pd.Series, pd.Series]:
    """A single-point deviation of `magnitude` (signed; can be negative) at position `at`."""
    perturbed = series.copy()
    mask = pd.Series(False, index=series.index)
    perturbed.iloc[at] += magnitude
    mask.iloc[at] = True
    return perturbed, mask


def inject_step_change(
    series: pd.Series, start: int, duration: int, magnitude: float
) -> tuple[pd.Series, pd.Series]:
    """A sustained level shift of `magnitude` for `duration` hours starting at `start` --
    every value in the window is shifted by the same amount, preserving the original
    shape/variation on top of the new level."""
    perturbed = series.copy()
    mask = pd.Series(False, index=series.index)
    end = start + duration
    perturbed.iloc[start:end] += magnitude
    mask.iloc[start:end] = True
    return perturbed, mask


def inject_flatline(
    series: pd.Series, start: int, duration: int
) -> tuple[pd.Series, pd.Series]:
    """A stuck-sensor: every value in the window is pinned to the value immediately before
    the window starts, regardless of what the real signal does."""
    perturbed = series.copy()
    mask = pd.Series(False, index=series.index)
    end = start + duration
    stuck_value = series.iloc[start - 1]
    perturbed.iloc[start:end] = stuck_value
    mask.iloc[start:end] = True
    return perturbed, mask


def inject_abnormal_ramp(
    series: pd.Series, start: int, duration: int, total_magnitude: float
) -> tuple[pd.Series, pd.Series]:
    """A sustained linear ramp added on top of the real signal, reaching `total_magnitude`
    by the end of the window -- simulates an unusually fast, sustained trend rather than a
    single-point or level-shift anomaly."""
    perturbed = series.copy()
    mask = pd.Series(False, index=series.index)
    end = start + duration
    ramp = np.linspace(0, total_magnitude, duration)
    perturbed.iloc[start:end] = perturbed.iloc[start:end].to_numpy() + ramp
    mask.iloc[start:end] = True
    return perturbed, mask


@dataclass(frozen=True)
class Injection:
    """One injection to apply. `kind` selects the injector; `kwargs` are passed through
    (minus `series`, which inject_many supplies)."""

    kind: str  # "spike" | "step_change" | "flatline" | "abnormal_ramp"
    kwargs: dict


_INJECTORS = {
    "spike": inject_spike,
    "step_change": inject_step_change,
    "flatline": inject_flatline,
    "abnormal_ramp": inject_abnormal_ramp,
}


def inject_many(series: pd.Series, injections: list[Injection]) -> tuple[pd.Series, pd.Series]:
    """Applies each injection in turn to a running copy of `series`, returns the final
    perturbed series and the UNION of all injected-position masks. Callers are responsible
    for choosing non-overlapping positions -- overlapping injections aren't an error, but
    the later one simply overwrites the earlier one's values at the shared positions."""
    perturbed = series.copy()
    combined_mask = pd.Series(False, index=series.index)
    for injection in injections:
        fn = _INJECTORS[injection.kind]
        perturbed, mask = fn(perturbed, **injection.kwargs)
        combined_mask |= mask
    return perturbed, combined_mask


def recall_at_budget(injected_mask: pd.Series, flagged_mask: pd.Series) -> float:
    """Of the positions actually injected, what fraction did the detector flag? Both masks
    must share an index. This is the one number Architecture.md Section 6 asks for:
    "report recall at a fixed alert budget" -- the budget itself is enforced upstream by
    Detector.calibrate_threshold, not here."""
    injected_count = int(injected_mask.sum())
    if injected_count == 0:
        raise ValueError("injected_mask has no True entries -- nothing was actually injected")
    aligned_flags = flagged_mask.reindex(injected_mask.index).fillna(False)
    caught = int((injected_mask & aligned_flags).sum())
    return caught / injected_count
