# PJM Grid Watch — Architecture

Repo: `pa-grid-monitor` (github.com/aaaaaron29/pa-grid-monitor).

## 1. What this project is

A real-time, actually-deployed grid-monitoring system for electricity price and load
anomalies on the PJM grid, with a correlation layer tying anomaly activity to data-center-
driven load growth in Pennsylvania — a live, current story given PJM's ongoing AI/data-center
load surge and the new FERC-approved Large Load Registry.

The goal is genuine end-to-end infrastructure (Kafka, Kubernetes, Prometheus/Grafana, CI/CD),
not a toy pipeline, paired with a deliberately rigorous ML methodology: a time-based
train/test split, since naive random splits on time-series/grid data are a well-known leakage
risk (information from the future leaking into training).

## 2. Scope decisions (locked in during planning — don't relitigate these mid-build)

- **Stack:** Python only. Deliberately not adding another language here — this project
  already stacks Kafka + Kubernetes + a trained model + Prometheus/Grafana; adding a new
  language on top risks becoming unfocused.
- **Model depth:** a real trained ML model (isolation forest for point anomalies, LSTM or
  similar for load forecasting), not just a rolling z-score. Must use a **time-based**
  train/test split (train on older data, evaluate on most recent) to avoid lookahead/leakage
  — document the methodology in the README, not just the code. Keep any description of the
  model honest — don't overclaim rigor beyond what was actually validated.
- **Interconnection-queue correlation is a CORE feature, not a stretch goal** — joining
  data-center siting/large-load queue data with zone-level grid stress is part of the main
  pipeline from day one.
- **Visualization:** Prometheus + Grafana (self-hosted on the same cluster), not Streamlit.
- **Deployment:** real Kubernetes (k3s), not just Docker Compose. Compose is for local dev only.
- **Hosting:** Oracle Cloud "Always Free" tier VM, chosen because it's the only realistic
  free option that can run a real, persistent, stateful stack (Kafka + Postgres + k3s)
  24/7 — Vercel was considered and rejected (serverless/static only, can't run long-running
  Kafka brokers or consumers).
- **Public/private data split (locked after legal check, see Section 3):** the live,
  publicly-hostable, shareable-with-anyone site runs entirely on **EIA data** (public domain,
  zero redistribution restriction, any audience size). **PJM Data Miner's zone-level LMP data
  stays a private research/analysis layer** — used for your own model development and the
  PA-zone-specific story, shown via screen-share/interview/README, never on the public
  dashboard. Don't blur this line mid-build; it's the difference between compliant and not.
- **Timeline:** open-ended — prioritize depth and quality over speed.
- **Stretch goals (in priority order, do core pipeline first):**
  1. CI/CD auto-deploy on push (GitHub Actions → build → push to live Oracle k3s cluster)
  2. Slack/email alerting on detected anomalies
  3. Terraform/IaC for the Oracle VM + k3s bootstrap

## 3. Known risks to resolve early (don't assume — verify in Phase 1)

- **Non-member API registration requires a manual email step, not instant self-service.**
  Per PJM's own Data Miner API Guide: after creating a PJM Tools account at
  `accountmanager.pjm.com` / `apiportal.pjm.com`, non-members must separately email
  `accountmanager@pjm.com` with the exact statement *"I confirm that the PJM Data will be
  used for internal business purposes only,"* including your Account Manager user id and the
  email used to subscribe. PJM then manually provisions non-member API access — expect a
  human-review turnaround delay. Do this first, well before you plan to start coding, not the
  night you want to start Phase 1.
- **Non-member redistribution restriction (confirmed from PJM's actual Data Miner 2 Terms of
  Use, Section 1):** "Members may republish data, however non-members are specifically
  prohibited from republishing data." Without an Associate Membership (a paid, company-level
  tier — a company-level commitment not worth taking on here), **the Grafana dashboard cannot be a fully
  public, open URL** — that likely counts as republishing. Internal/personal use, local
  development, and screen-shared/recorded demos are fine. Keep the live deployment
  access-gated (basic auth or similar) rather than an open public link.
- **Non-member rate limit is 6 requests/minute** (members get 600/min), per the same Terms of
  Use (Section 2). Irrelevant at a 5-minute polling cadence — just don't poll aggressively
  or in a tight retry loop during debugging.
- **Use the `gridstatus` Python library (`pip install gridstatus`) instead of hand-rolling
  PJM API calls.** It's an actively maintained open-source wrapper that already handles PJM
  LMP, load, and — notably — interconnection-queue data, which may remove most of the custom
  queue-scraper work planned in Phase 1. It expects your key as the `PJM_API_KEY` env var.
  Check its current PJM module first in Phase 1 before building anything custom.
- **PJM API auth may require more than a plain API key now.** PJM is rolling out a new
  PKI-certificate-based authentication requirement for Data Miner API users (full rollout
  targeted Q3 2026 per PJM's own tech-change documentation) — meaning this may already be
  live by the time you build. Read PJM's "PKI-Based Authentication Guide" during
  registration, don't assume the old API-key-only flow still works. If `gridstatus` handles
  this transparently, that's another reason to prefer it over custom integration.
- **The Large Load Registry (data-center interconnection transparency) was only approved by
  FERC on 2026-10-09** — days before this doc was written. The actual public data access
  mechanism (API vs. CSV export vs. committee PDF disclosures) may not be fully operational
  yet. Budget real investigation time in Phase 1 to find the actual current data source;
  don't assume a clean API exists. Fallback: PJM's planning-committee queue documents
  (CIFP-LLA package materials, board disclosure PDFs) are public but are periodic
  PDFs/spreadsheets, not a live feed — treat queue ingestion as **batch**, not streaming,
  regardless of which source wins.
- **Oracle's Always Free compute was quietly cut in July 2026** — now 2 OCPUs / 12GB RAM
  total (ARM Ampere A1), down from the historical 4/24. This is still enough for a lean
  single-node k3s running Kafka (KRaft mode, no Zookeeper), Postgres, the inference service,
  and Prometheus/Grafana — but there's little headroom; keep images small and avoid running
  anything redundant.
- **Oracle reclaims idle Always Free instances** if CPU, network, and memory utilization are
  all under 20% for 95% of a rolling 7-day window. A pipeline that just polls an API every
  5 minutes and idles otherwise is at real risk of looking "idle" to Oracle's reclamation
  check. Mitigate with either a deliberate low-level synthetic/keepalive load, or accept the
  risk and keep the Terraform/redeploy story ready so losing the instance is a non-event.
  If this becomes a real problem, Fly.io or Railway's free tiers are fallback hosts.
- **PJM "real-time" LMP data refreshes on a 5-minute cadence**, not sub-second — "streaming"
  here means polling-to-Kafka at that cadence, not a true continuous event stream. Be
  accurate about this in the project's documentation.

## 4. Data sources

### Public tier (feeds the public dashboard — legally unrestricted, any audience)

- **EIA Open Data API** (`eia.gov/opendata`) — free, instant registration, U.S. federal
  government data (public domain, no copyright, no redistribution restriction, no membership
  tier). Use the **Hourly Electric Grid Monitor (EIA-930)** dataset: hourly demand, net
  generation, and interchange for PJM as a Balancing Authority. This is PJM's whole
  multi-state footprint, not broken into PA-specific zones — that granularity loss is the
  price of this data being safely public.

### Private tier (research/analysis only — never exposed on the public dashboard)

- **PJM Data Miner 2** (`apiportal.pjm.com`) — real-time + historical locational marginal
  pricing (LMP) and load data, broken out by zone. Register for a PJM tools account via
  `accountmanager.pjm.com`, then follow the non-member email provisioning process (Section 3,
  Section 8). Check the PKI auth requirement before assuming a bare API key is sufficient.
  Use this for the PA-zone-specific analysis and your own model development; keep its Grafana
  dashboard authenticated-only, never a public link.
- **PA zones to monitor:** PECO, PPL, METED, PENELEC, and DUQ (Duquesne Light) — these cover
  Pennsylvania within PJM's transmission zone map.
- **Data-center / large-load interconnection data** — source TBD at build time. Start with
  the new FERC-approved Large Load Registry (a public regulatory transparency record, not
  Data Miner Tool output — a different legal basis, so not obviously bound by Data Miner's
  Terms of Use) and PJM's openly-posted planning-committee disclosure PDFs (posted directly
  on pjm.com, not gated behind the Data Miner Tool). Confirm actual access mechanism in
  Phase 1 — don't assume a clean API exists yet, this was only approved 2026-10-09.

## 5. System architecture

Two parallel pipelines share the same Kafka/Postgres/Grafana infra, but stay data-isolated
because only one of them is legally safe to expose publicly.

```
PUBLIC PIPELINE (safe to expose — powers the public dashboard)
─────────────────────────────────────────────────────────────
  ┌───────────────────┐
  │  EIA-930 API       │  (hourly BA-level demand/generation/interchange)
  └─────────┬──────────┘
            │ poll
            ▼
  ┌───────────────────┐      ┌───────────────────┐      ┌───────────────────┐
  │ EIA poller service │─────▶│ Kafka: eia.grid.raw│─────▶│ Inference service │
  └───────────────────┘      └───────────────────┘      │ (isolation forest/│
                                                          │  LSTM, time-based │
                                                          │  split)           │
                                                          └─────────┬─────────┘
                                                                    ▼
                                                          ┌───────────────────┐
                                                          │ Postgres:         │
                                                          │ eia_readings      │
                                                          └─────────┬─────────┘
                                                                    ▼
                                                   Grafana "Public" dashboard —
                                                   shared via Grafana's native
                                                   PUBLIC DASHBOARD link feature
                                                   (only this dashboard, nothing
                                                   else in the instance)

PRIVATE PIPELINE (research/analysis only — never a public link)
─────────────────────────────────────────────────────────────
  ┌───────────────────┐      ┌──────────────────────┐
  │ PJM Data Miner API │      │ Queue / Large Load    │
  │ (PA zone LMP,      │      │ Registry (batch,      │
  │ 5-min refresh)     │      │ cron/K8s CronJob)      │
  └─────────┬──────────┘      └───────────┬───────────┘
            ▼                              ▼
  ┌───────────────────┐      ┌───────────────────────┐
  │ Kafka: pjm.lmp.raw │      │ Postgres:             │
  └─────────┬──────────┘      │ interconnection_queue │
            ▼                 └───────────┬───────────┘
  ┌───────────────────┐                   │
  │ Inference service  │                   │
  └─────────┬──────────┘                   │
            ▼                              │
  ┌───────────────────┐◄──────────────────┘
  │ Postgres:          │  periodic join job
  │ lmp_readings,      │
  │ zone_stress_vs_dc  │
  └─────────┬──────────┘
            ▼
  Grafana "Private" dashboard — normal authenticated Grafana login only,
  no public dashboard sharing enabled. Also feeds:
            │
            ▼
  ┌───────────────────┐      ┌───────────────────────┐
  │ Kafka:             │─────▶│ Alerting service       │
  │ pjm.lmp.anomalies  │      │ (stretch: Slack/email) │
  └───────────────────┘      └───────────────────────┘

Prometheus scrapes /metrics from both pollers + both inference services.
```

All of the above runs as Kubernetes workloads (k3s) on a single Oracle Cloud Always Free VM.
Docker Compose reproduces the same stack locally for day-to-day development.

## 6. Proposed repo structure

```
/ingestion
  eia_poller/        public-tier poller (EIA-930)
  pjm_poller/        private-tier poller (PJM Data Miner)
  queue_scraper/     interconnection/Large Load Registry batch job
/inference           FastAPI service(s), model loading, serving (both tiers)
/model               training scripts, time-based split logic, saved model artifacts
/alerting            stretch: Slack/email notifier (private tier only)
/infra
  docker-compose.yml   local dev stack
  /k8s               plain manifests (or Helm charts) for every service above,
                     including Grafana public-dashboard config for the public tier only
  /terraform          stretch: Oracle VM + k3s bootstrap
/.github/workflows/ci.yml
README.md             documents the public/private data split explicitly for anyone
                       reading the repo (including why)
```

## 7. Build phases

1. **Ingestion + storage** — EIA poller (public tier) first since it's unblocked and
   zero-risk; PJM poller (private tier) once non-member access is provisioned; queue
   scraper/Large Load Registry once its access mechanism is confirmed. Postgres schema for
   all three. Confirm the PKI auth question and the Large Load Registry data source here
   first — don't proceed past this phase on unverified assumptions.
2. **Model** — train isolation forest (+ optionally an LSTM forecast) per tier, time-based
   split, write up the methodology honestly (what was validated, what wasn't).
3. **Pipeline wiring** — Kafka producers/consumers for both tiers, FastAPI inference
   service(s), Docker Compose local stack end-to-end.
4. **Observability** — Prometheus + two Grafana dashboards: the public one (EIA-only data,
   shared via Grafana's public-dashboard link feature) and the private one (PJM zone data +
   data-center correlation, authenticated access only). Double-check the public dashboard
   genuinely has zero PJM-sourced panels before enabling its public link.
5. **Deploy** — Kubernetes manifests, Oracle Cloud VM + k3s, live 24/7.
6. **Stretch** (in priority order) — CI/CD auto-deploy, Slack/email alerting, Terraform IaC.

## 8. Steps to complete before building starts

These are the only external dependencies — everything else (Kafka, Postgres, Grafana, k3s,
Docker, GitHub Actions) is self-installed later and needs no advance signup.

1. **Register for an EIA API key** — `eia.gov/opendata`, free, instant, no approval wait.
   Unblocks the entire public tier immediately.
2. **Create a PJM Tools account** — via `accountmanager.pjm.com/accountmanager/pages/public/new-user.jsf`
   or `apiportal.pjm.com`. This alone does not grant API access yet.
3. **Send the non-member provisioning email** — to `accountmanager@pjm.com`, containing:
   - The exact statement: *"I confirm that the PJM Data will be used for internal business
     purposes only."*
   - Your Account Manager user id
   - The email address you used to register
   Do this as early as possible — turnaround time is unknown and this is the one step with
   external human review. Don't wait until you're ready to code the private-tier poller.
4. **Check whether PKI-certificate auth is now required** for Data Miner API users (PJM's own
   roadmap targeted full rollout for Q3 2026, which has likely already passed) — read the
   PKI-Based Authentication Guide linked from PJM's API documentation when you get your API
   portal access, and note whether `gridstatus` (the Python library) handles it for you.
5. **Create an Oracle Cloud account** for the Always Free tier VM. Oracle may ask for a card
   for identity verification even on the free tier — it should not charge unless you
   explicitly upgrade, but confirm this during signup before proceeding.
6. **Create the GitHub repo** for this project — needed before the CI/CD stretch goal, but
   fine to do whenever convenient.

Nothing above requires deep technical setup yet — steps 1, 2, 5, and 6 can be done in minutes;
step 3 is the one to kick off first since it's the only one with an unknown wait.
