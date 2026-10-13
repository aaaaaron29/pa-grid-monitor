#!/usr/bin/env python
"""Quick local status page for Phase 1 ingestion — NOT the Phase 4 Grafana dashboard
Architecture.md describes. This is a throwaway dev convenience: "is data flowing, how much
do we have, how fresh is it" at a glance while backfills/pollers run, using only what's
already a dependency (psycopg, stdlib http.server). Delete it once Grafana exists.

Usage: python scripts/dashboard.py [--port 8787]
Then open http://localhost:8787
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402

EIA_QUERY = """
SELECT reading_type, count(*), min(period_start), max(period_start), max(retrieved_at)
FROM eia_readings GROUP BY reading_type ORDER BY reading_type
"""

PJM_QUERY = """
SELECT
    zone,
    count(*) FILTER (WHERE verified) AS verified_rows,
    count(*) FILTER (WHERE NOT verified) AS unverified_rows,
    count(*) AS total_rows,
    min(period_start),
    max(period_start),
    max(retrieved_at)
FROM pjm_lmp_readings GROUP BY zone ORDER BY zone
"""


def _age_str(ts) -> str:
    if ts is None:
        return "never"
    delta = datetime.now(UTC) - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _freshness_class(ts, stale_after_secs: int = 3600) -> str:
    if ts is None:
        return "stale"
    age = (datetime.now(UTC) - ts).total_seconds()
    return "fresh" if age < stale_after_secs else "stale"


def render(dsn: str) -> str:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(EIA_QUERY)
        eia_rows = cur.fetchall()
        cur.execute(PJM_QUERY)
        pjm_rows = cur.fetchall()

    eia_total = sum(r[1] for r in eia_rows)
    pjm_total = sum(r[3] for r in pjm_rows)

    def eia_tr(r):
        reading_type, count, pmin, pmax, retrieved = r
        cls = _freshness_class(retrieved)
        return f"""<tr>
            <td>{reading_type}</td><td>{count:,}</td>
            <td>{pmin}</td><td>{pmax}</td>
            <td class="{cls}">{_age_str(retrieved)}</td>
        </tr>"""

    def pjm_tr(r):
        zone, verified, unverified, total, pmin, pmax, retrieved = r
        cls = _freshness_class(retrieved, stale_after_secs=900)
        return f"""<tr>
            <td>{zone}</td><td>{total:,}</td>
            <td>{verified:,}</td><td>{unverified:,}</td>
            <td>{pmin}</td><td>{pmax}</td>
            <td class="{cls}">{_age_str(retrieved)}</td>
        </tr>"""

    eia_body = "\n".join(eia_tr(r) for r in eia_rows) or "<tr><td colspan=5>no data yet</td></tr>"
    pjm_body = "\n".join(pjm_tr(r) for r in pjm_rows) or "<tr><td colspan=7>no data yet</td></tr>"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>pjm-grid-watch: local status</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; background: #0f1115; color: #e4e6eb;
          max-width: 960px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.3rem; }}
  h2 {{ font-size: 1.05rem; margin-top: 2rem; color: #9aa4b2; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 0.5rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.7rem; border-bottom: 1px solid #262a33;
            font-size: 0.9rem; }}
  th {{ color: #7d8694; font-weight: 600; }}
  .fresh {{ color: #4ade80; }}
  .stale {{ color: #f87171; }}
  .totals {{ color: #9aa4b2; font-size: 0.85rem; }}
  .meta {{ color: #5c6472; font-size: 0.75rem; margin-top: 2rem; }}
</style>
</head>
<body>
  <h1>pjm-grid-watch - local ingestion status</h1>
  <p class="totals">EIA: {eia_total:,} rows &nbsp;|&nbsp; PJM: {pjm_total:,} rows &nbsp;|&nbsp;
     page refreshes every 5s</p>

  <h2>EIA (public tier)</h2>
  <table>
    <tr><th>reading_type</th><th>rows</th><th>earliest</th><th>latest</th><th>last write</th></tr>
    {eia_body}
  </table>

  <h2>PJM (private tier)</h2>
  <table>
    <tr><th>zone</th><th>rows</th><th>verified</th><th>unverified</th>
        <th>earliest</th><th>latest</th><th>last write</th></tr>
    {pjm_body}
  </table>

  <p class="meta">dev-only status page, not the real dashboard (Architecture.md Phase 4) -
     generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    dsn: str = ""

    def log_message(self, format, *args):  # noqa: A002 - quiet the default access log
        pass

    def do_GET(self):
        try:
            body = render(self.dsn).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            msg = f"<h1>error</h1><pre>{exc}</pre>".encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    settings = get_settings()
    Handler.dsn = settings.postgres_dsn

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving on http://localhost:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
