#!/usr/bin/env python
"""Applies infra/sql/*.sql in filename order, tracked in schema_migrations. Plain SQL files,
no framework (Architecture.md Section 7). Safe to re-run: each file is wrapped in a
transaction and skipped if its version is already recorded.

Usage: python scripts/apply_migrations.py [--dsn postgresql://...]
Defaults to common.config.Settings().postgres_dsn (i.e. POSTGRES_DSN / .env).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from common.logging import configure_logging  # noqa: E402

log = logging.getLogger("apply_migrations")
SQL_DIR = Path(__file__).resolve().parent.parent / "infra" / "sql"


def already_applied(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
        )
        (exists,) = cur.fetchone()
        if not exists:
            return set()
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migrations(dsn: str) -> None:
    """Apply every infra/sql file not yet recorded in schema_migrations. Importable so other
    scripts (the Neon sync) can make sure a target database has the current schema first."""
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        log.warning("no migration files found", extra={"dir": str(SQL_DIR)})
        return

    with psycopg.connect(dsn, autocommit=False) as conn:
        applied = already_applied(conn)
        for path in files:
            version = path.stem
            if version in applied:
                log.info("skip (already applied)", extra={"version": version})
                continue
            log.info("applying", extra={"version": version})
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
            conn.commit()
            log.info("applied", extra={"version": version})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    apply_migrations(args.dsn or get_settings().postgres_dsn)


if __name__ == "__main__":
    main()
