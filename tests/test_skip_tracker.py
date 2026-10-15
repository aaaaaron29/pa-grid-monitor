from __future__ import annotations

import logging

from inference.skip_tracker import SkipTracker

LOGGER = "test.skip_tracker"


def _tracker() -> SkipTracker:
    return SkipTracker(logging.getLogger(LOGGER))


def test_the_first_skip_is_a_warning(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    _tracker().skipped("PECO", period_start="2026-10-13T00:00:00+00:00")

    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert caplog.records[0].scope == "PECO"
    assert "scoring halted" in caplog.records[0].getMessage()


def test_repeated_skips_do_not_repeat_the_warning(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    tracker = _tracker()

    for _ in range(50):
        tracker.skipped("PECO")

    assert len(caplog.records) == 1


def test_each_scope_is_tracked_separately(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    tracker = _tracker()

    tracker.skipped("PECO")
    tracker.skipped("PPL")

    assert [r.scope for r in caplog.records] == ["PECO", "PPL"]


def test_resuming_is_logged_once_and_re_arms_the_warning(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    tracker = _tracker()
    tracker.skipped("PECO")
    caplog.clear()

    tracker.scored("PECO")
    tracker.scored("PECO")  # a second success must not log again
    assert [r.getMessage() for r in caplog.records] == ["scoring resumed"]

    caplog.clear()
    tracker.skipped("PECO")  # a new halt after recovery warns again
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_scoring_normally_logs_nothing(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    _tracker().scored("PECO")

    assert caplog.records == []
