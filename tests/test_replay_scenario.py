"""The CI replay scenario (scripts/replay), checked offline against the real scoring code.

The replay job pushes this scenario through Kafka, the consumer, Postgres and the inference
service in a cluster. These tests run the same series through the scoring functions alone, so
a bad scenario (planted events that are not flagged, or flags nowhere near them) fails here in
seconds instead of after a cluster has been built, and they pin the bug the replay was built to
catch: a hole in stored history moved the seasonal-naive forecast onto the wrong time of day.
"""
from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import pandas as pd
import pytest

from inference.pjm_service import _score_and_store
from model.score import has_context, score_latest, score_since
from scripts.replay import data
from scripts.replay.make_artifact import TRAIN_BACK, clean_series, fit


@pytest.fixture(scope="module")
def artifact():
    series = clean_series(-data.LAG - TRAIN_BACK, data.HISTORY + data.LIVE)
    return fit(data.ZONE, series)


def scenario_grid() -> pd.Series:
    """What Postgres holds after the replay: history, then the live window minus the outage."""
    idx = pd.date_range(data.when(0), periods=data.HISTORY + data.LIVE, freq="5min", tz="UTC")
    values = [np.nan if i in data.OUTAGE else data.value(i) for i in range(len(idx))]
    return pd.Series(values, index=idx)


def live_scores(artifact) -> dict[int, dict]:
    """Score each published interval the way the inference service does: a window of stored
    history ending just before it (holes left as NaN), plus the new value."""
    grid = scenario_grid()
    window = data.LAG + 1 + 30
    out = {}
    for i in data.live_indices():
        series = grid.iloc[max(0, i - window) : i + 1]  # before T0 there is nothing stored
        out[i] = score_latest(series, artifact)
    return out


@pytest.fixture(scope="module")
def live(artifact):
    return live_scores(artifact)


def test_the_detector_flags_exactly_what_was_planted(live):
    rows = {i: r for i, r in live.items() if has_context(r)}
    forest = {i for i, r in rows.items() if r["forest_flagged"]}
    flatline = {i for i, r in rows.items() if r["flatline_flagged"]}
    assert forest == data.EXPECTED_FOREST
    assert flatline == data.EXPECTED_FLATLINE


def test_only_the_intervals_after_the_outage_lose_their_context(live):
    """The weekly lag still lands on a real reading everywhere, so the only points left
    unscored are those whose recent window is incomplete: the outage's tail."""
    declined = {i for i, r in live.items() if not has_context(r)}
    assert declined == data.EXPECTED_DECLINED


def test_batch_rescoring_agrees_with_live_scoring_except_early_in_a_flat_stretch(artifact, live):
    """score_since (the daily heal) and score_latest (the live service) are meant to give the
    same answer for every point. They do for prices and declines. They differ on a stuck
    sensor: the batch rule counts the whole run, including rows after the one being judged, so
    it flags the early rows of the stretch that live scoring could not yet know about."""
    base = pd.Timestamp(data.T0)
    since = pd.Timestamp(data.when(data.LIVE_START))
    batch = {
        int((r["period_start"] - base) / pd.Timedelta(minutes=5)): r
        for r in score_since(scenario_grid(), artifact, since)
    }
    flat_start = data.EVENTS[2].start
    for i, r in live.items():
        b = batch[i]
        assert b["forest_flagged"] == r["forest_flagged"]
        assert has_context(b) == has_context(r)
        if not (flat_start <= i < flat_start + data.FLAT_LEN):
            assert b["flatline_flagged"] == r["flatline_flagged"]
    retroactive = {
        i for i in live if batch[i]["flatline_flagged"] and not live[i]["flatline_flagged"]
    }
    assert retroactive == set(range(flat_start + 10, flat_start + 10 + data.ROLLING_WINDOW - 1))


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@contextmanager
def _fake_connect(dsn):
    yield _Conn()


def test_a_hole_in_stored_history_does_not_shift_the_weekly_forecast(artifact, monkeypatch):
    """Regression for the bug the replay exposed. The inference service dropped excluded
    periods from the series before the row-count shift, so after any hole longer than the
    forward fill, "same time last week" pointed at a different time of day. On this noise-free
    series the true residual is exactly zero, so any other value is the bug."""
    n = data.LAG + 400
    idx = pd.date_range(data.when(0), periods=n, freq="5min", tz="UTC")
    cycle = np.sin(2 * np.pi * (np.arange(n) % 288) / 288)
    smooth = pd.Series(data.BASE_LEVEL + data.DAILY_SWING * cycle, index=idx)
    current = data.LAG + 200
    hole = slice(current - 120, current - 100)  # 20 missing intervals, well before the point
    stored = smooth.copy()
    stored.iloc[hole] = np.nan
    stored = stored.iloc[:current]

    written = []
    monkeypatch.setattr("inference.pjm_service.load_pjm_series", lambda *a, **k: stored)
    monkeypatch.setattr("inference.pjm_service.connect", _fake_connect)
    monkeypatch.setattr(
        "inference.pjm_service.upsert_pjm_lmp_anomalies", lambda conn, rows: written.extend(rows)
    )
    row = {
        "zone": data.ZONE,
        "period_start": idx[current].isoformat(),
        "lmp_price": float(smooth.iloc[current]),
    }
    _score_and_store(settings=_Settings(), artifacts={data.ZONE: artifact}, row=row)

    assert len(written) == 1
    assert written[0]["residual"] == pytest.approx(0.0, abs=1e-9)


def test_a_point_whose_week_ago_reading_is_missing_is_declined(artifact):
    """If the exact reading one lag earlier is absent there is no forecast, and the answer is
    a null residual, not a different time's value standing in for it."""
    n = data.LAG + 50
    idx = pd.date_range(data.when(0), periods=n, freq="5min", tz="UTC")
    series = pd.Series(100.0 + np.random.default_rng(1).normal(0, 1, n), index=idx)
    series.iloc[n - 1 - data.LAG] = np.nan  # the reading exactly one lag before the last point
    result = score_latest(series, artifact)
    assert not has_context(result)


class _Settings:
    postgres_dsn = "unused"
