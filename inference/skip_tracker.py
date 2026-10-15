"""Makes a silent scoring failure audible without flooding the log.

The inference services decline to score a reading when the stored history before it has a hole
(they need about a week of dense history). That used to be logged at DEBUG, so a gap of any
size left the dashboards without a forecast or residuals and nothing anywhere said so. It went
unnoticed for days. A line per skipped reading would be too much (one per zone every five
minutes), so this logs a WARNING when scoring stops for a given key, and an INFO when it
resumes. The per-reading skip counter in common.metrics is unchanged.
"""
from __future__ import annotations

import logging


class SkipTracker:
    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        self._halted: set[str] = set()

    def skipped(self, scope: str, **context: object) -> None:
        """Call each time a reading is skipped. Only the first skip in a run is logged."""
        if scope in self._halted:
            return
        self._halted.add(scope)
        self._log.warning(
            "scoring halted: not enough settled history before this reading; the stored "
            "readings probably have a gap, so there will be no forecast or residuals until "
            "it is backfilled (python -m ingestion.backfill) or ages out of the window",
            extra={"scope": scope, **context},
        )

    def scored(self, scope: str) -> None:
        """Call each time a reading is scored. Logs once when scoring resumes after a halt."""
        if scope in self._halted:
            self._halted.discard(scope)
            self._log.info("scoring resumed", extra={"scope": scope})
