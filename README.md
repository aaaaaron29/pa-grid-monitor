# pa-grid-monitor

Anomaly detection on the PJM electricity grid, plus a public map of publicly reported data
center projects in Pennsylvania and a passcode-gated analysis layer that sets zone-level grid
stress beside them.

**Live site:** https://gridwatchpa.vercel.app/

**Status.** The pipeline (ingestion, Kafka, Postgres, two inference services, Prometheus,
Grafana) is built and CI-verified end to end, and the Kubernetes manifests are validated
against a real cluster in CI. The frontend is built and deployed. Since 2026-10-16 the
pipeline runs around the clock on a single small VPS under Docker Compose
([deploy/vps/](deploy/vps/)) rather than a cluster or a personal machine. That stack leaves
out Prometheus and Grafana, which the website replaced, so they run only in the local
development setup. The live site's private pages are only as fresh as the last hourly sync
from the server, and the private pipeline page shows when the last one arrived. No alert
channel is configured yet, so a dead server is noticed only by someone looking at that page. The full correlation layer between grid stress and data center interconnection
activity is not built.

## What it does

Polls grid data on a schedule into Kafka and Postgres, forecasts what demand should be,
flags the intervals where reality diverges from that forecast, and shows the result on a
website and in Grafana.

Data arrives by scheduled polling, not a continuous event stream: EIA publishes on a
multi-hour lag and PJM refreshes every five minutes.

## The website

A Next.js app in [frontend/](frontend/).

| Route | Access | Contents |
|---|---|---|
| `/` | Public | Case study and methodology |
| `/demand` | Public | PJM-wide hourly demand against the forecast, from EIA data |
| `/map` | Public | Pennsylvania data center map (below) |
| `/private/*` | Passcode | PA zone prices, anomalies, forecast accountability, map with a zone overlay, and pipeline health (stream freshness, daily completeness, website-copy parity, server state) |

### The data center map

An interactive map of publicly reported data center projects in Pennsylvania.

- **Status model.** Each project is Announced, Under local review, Approved for a first
  phase, Under construction, Rejected locally, or Abandoned. Each status has its own marker
  shape as well as a color, and filter chips show live counts.
- **Search, sortable table and shareable links.** The selected project, status filters and
  search are kept in the URL.
- **Who and what is nearby.** For projects placed at a specific site, the panel gives
  2020 Census people and homes within half a mile to five miles, the nearest homes, and
  schools, hospitals, nursing homes and child care within a mile. Optional 1 and 5 mile rings
  zoom the map to the site. Existing housing only. Projects located only to a municipality
  show "not measured".
- **Power plants.** An optional layer of operating plants of 100 MW or more, and the nearest
  plant for each measured project.
- **Local response.** Notes on public comment, votes and opposition, only where a source was
  read, each with a link and date.
- **Proximity is not impact.** The map shows who lives near a marker. It does not forecast
  noise, water use, emissions or rates, and there is no risk score.

The project list is hand-curated and is not a registry: there is no authoritative public
dataset of these projects. An entry is added only when a news article, company release or
similar source was read and supports its status, and each entry carries an as-of date and its
sources. Statuses go stale quickly, so treat the date as part of the data. Project data is in
[scripts/map/data_centers.json](scripts/map/data_centers.json), and
`python scripts/map/build_map_data.py` regenerates the frontend data files from it (county
and utility by point-in-polygon, exposure from Census blocks, facilities and plants from
HIFLD). `python scripts/map/locate.py` finds coordinates for a new project.

Sources: U.S. Census 2020 redistricting files and county geometry, and HIFLD retail service
territories, power plants and facilities as served by Penn State's PASDA.

## Two data tiers, and why

|  | Public tier | Private tier |
|---|---|---|
| **Source** | EIA-930 Hourly Electric Grid Monitor | PJM Data Miner 2 |
| **Granularity** | PJM-wide, hourly | PA zones (PECO, PPL, METED, PENELEC, DUQ), 5-minute |
| **Visibility** | Open site and this repository | Passcode-gated pages only |

PJM's Data Miner terms prohibit non-members from republishing its data, so everything
publicly visible here (the public routes and this repository) is built exclusively on EIA's U.S. federal public-domain data, public geography and public reporting.
The PJM tier exists for zone-level analysis and is demonstrated behind a passcode rather than
published: **no raw PJM values, sample rows, screenshots, or PJM-trained model artifacts
appear in this repo.** Code, schema, methodology, and aggregate findings do.

## Methodology

- **Time-based split**, never shuffled: scalers and thresholds fit on the training window
  only, since leakage on time-series data usually enters through the scaler rather than the
  model.
- **The detector scores forecast residuals, not raw demand.** Scoring raw levels just
  rediscovers that summer afternoons are hot; scoring residuals makes an anomaly mean "the
  grid did something the model didn't expect."
- **No ground-truth anomaly labels exist for this data**, and the write-up says so rather
  than reporting a precision figure that can't be computed. Evaluation is: forecast error
  against published baselines, synthetic-anomaly injection at a fixed alert budget, and
  qualitative correspondence with known grid events.
- Ingest is revision-aware: EIA restates published figures, and training on revised history
  while serving on unrevised values is train/serve skew.

Full reasoning, including what is deliberately *not* claimed, is in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Running it

- **Pipeline:** Postgres, Kafka, a poller and consumer per source, and the inference services.
  The PJM poller shares one cross-process rate limit because the API allows 6 requests per
  minute per key.
- **Database for the site:** the pipeline writes to its own Postgres, and
  `scripts/sync_to_neon.py` copies new rows to a Neon database on an hourly schedule. Neon's
  free plan would run out of compute hours if the pipeline wrote to it directly every five
  minutes. See ARCHITECTURE.md for the reasoning.
- **On a server:** [deploy/vps/](deploy/vps/) is the production setup: a Compose stack that
  publishes nothing but SSH, restarts itself, and is checked every five minutes by `ops.sh`,
  which starts what is down, restarts what is stuck, alerts when a data stream stops arriving,
  and once a day re-pulls the last few days from PJM's verified feed and re-scores them, which
  closes the gaps an outage leaves. Its README has the setup and cutover steps.
- **On a Windows machine:** `scripts/windows/install_watchdog.ps1` registers a scheduled task
  that does the same job for a pipeline run by hand, and `scripts/windows/watchdog.ps1 -Status`
  prints the state without changing anything.
- **Frontend:** `cd frontend && npm install && npm run dev`, with `DATABASE_URL` and
  `PRIVATE_PASSCODE` set in `frontend/.env.local` (see `.env.example`; gitignored, never
  commit it). The public map needs neither.
- **Checks:** `pytest`, `ruff check .`, and in `frontend/`: `npx tsc --noEmit`, `npm run lint`
  and `npm run build`.

Private pages sit behind a passcode with a database-backed lockout: three failures from one
address lock it out for 15 minutes, and the check fails closed.

## Stack

Python · Kafka (KRaft) · Postgres · Neon · scikit-learn · FastAPI · Docker Compose ·
Prometheus · Grafana · Next.js · Tailwind · Vercel · GitHub Actions · GitHub Pages ·
Kubernetes (k3s manifests validated in CI)
