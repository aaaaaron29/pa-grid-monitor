# PJM Grid Watch — Architecture

Repo: `pa-grid-monitor` (github.com/aaaaaron29/pa-grid-monitor).

## 1. What this project is

A near-real-time, actually-deployed grid-monitoring system for electricity price and load
anomalies on the PJM grid, with a correlation layer tying anomaly activity to data-center-
driven load growth in Pennsylvania — a live, current story given PJM's ongoing AI/data-center
load surge and the new FERC-approved Large Load Registry.

The goal is genuine end-to-end infrastructure (Kafka, Kubernetes, Prometheus/Grafana, CI/CD),
not a toy pipeline, paired with a deliberately rigorous ML methodology: a time-based
train/test split, since naive random splits on time-series/grid data are a well-known leakage
risk (information from the future leaking into training).

"Near-real-time" is deliberate wording: EIA-930 publishes on a multi-hour lag and PJM
refreshes every five minutes, so this is frequent polling, not a continuous event stream.
The project claims what it actually does — see Section 3.

## 2. Scope decisions (locked in during planning — don't relitigate these mid-build)

- **Stack:** Python only. Deliberately not adding another language here — this project
  already stacks Kafka + Kubernetes + a trained model + Prometheus/Grafana; adding a new
  language on top risks becoming unfocused.
- **Model depth:** a real trained ML model (isolation forest for anomaly scoring, LSTM or
  similar for load forecasting), not just a rolling z-score. **The detector scores forecast
  residuals, not raw demand levels** — see Section 6, "Feature design"; this is the decision
  that makes an anomaly mean "the grid did something unexpected" rather than "it was hot". Must use a **time-based**
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
  PA-zone-specific story, shown live via screen-share/interview, never on the public
  dashboard. Don't blur this line mid-build; it's the difference between compliant and not.
- **Publication policy — the public GitHub repo counts as publishing.** Anything committed
  is world-readable, which is the same act Section 3's restriction prohibits, so "it's only
  in the README" is not a safe harbour. The rule: **no raw PJM values, no sample rows, no
  LMP screenshots, and no PJM-trained model artifacts in the repo.** What *is* publishable
  is the work that isn't the data — code, schema, methodology, and aggregate findings
  stated in prose ("PECO showed N anomalous intervals in Q1"). The private dashboard is
  demonstrated live, never captured into the repo. The goal isn't to obscure the data, it's
  to not republish it; derived aggregates and methodology are genuinely a different thing,
  and that distinction holds up under scrutiny in a way obfuscation wouldn't.
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
  human-review turnaround delay. **Status: confirmed live (2026-10-13)** — a real
  `Ocp-Apim-Subscription-Key` now authenticates against `api.pjm.com` (verified directly:
  HTTP 200 against `rt_hrl_lmps/metadata` and others, real data returned). The private tier
  is unblocked; see the new "PJM Data Miner: confirmed feed behavior" entry below for what
  that access actually looks like.
- **Grafana's public-sharing feature is confirmed available in OSS, no extra licensing
  needed.** It's officially called "Externally Shared Dashboards" (formerly "Public
  Dashboards") as of recent Grafana versions, enabled by default, and works per-dashboard —
  exactly the isolation this design needs. Requires Admin or the `dashboards.public:write`
  permission to enable on a given dashboard. Note the mechanism: a shared dashboard re-runs
  its stored queries against the live datasource on each public view, so make certain the
  "Public" dashboard's queries only ever touch the `eia_readings` table — never point a
  public-shared panel at anything PJM-sourced.
- **Non-member redistribution restriction (confirmed from PJM's actual Data Miner 2 Terms of
  Use, Section 1):** "Members may republish data, however non-members are specifically
  prohibited from republishing data." Without an Associate Membership (a paid, company-level
  tier — a company-level commitment not worth taking on here), **any PJM-fed dashboard
  cannot be a fully public, open URL** — that likely counts as republishing. Internal/personal use, local
  development, and screen-shared/recorded demos are fine. **Scope: this binds PJM-sourced
  data only.** It is why the private dashboard stays behind Grafana auth and is never
  externally shared — it is *not* a reason to gate the public tier, which is EIA-only
  (U.S. federal public domain) and is meant to be an open, linkable URL.
- **Non-member rate limit is 6 requests/minute** (members get 600/min), per the same Terms of
  Use (Section 2) — **and empirically confirmed**: testing the live key tripped a 429 after
  ~6 metadata/data calls inside a couple of minutes. It's real and it bites fast; back off
  aggressively, especially while exploring feeds by hand. Irrelevant at a 5-minute polling
  cadence for the poller itself — it matters for the historical backfill, where the
  per-request page size determines whether that job takes minutes or hours (Section 6).
- **Use the `gridstatus` Python library (`pip install gridstatus`) instead of hand-rolling
  PJM API calls.** It's an actively maintained open-source wrapper that already handles PJM
  LMP, load, and — notably — interconnection-queue data, which may remove most of the custom
  queue-scraper work planned in Phase 1. It expects your key as the `PJM_API_KEY` env var.
  Check its current PJM module first in Phase 1 before building anything custom.
- **PJM API auth: confirmed a plain subscription key is still sufficient (2026-10-13).** A
  bare `Ocp-Apim-Subscription-Key` header authenticated successfully against multiple live
  Data Miner 2 endpoints — no PKI client certificate was required despite PJM's Q3 2026
  rollout target for that requirement. Either the rollout hasn't reached non-member API-key
  auth, or this key predates/is exempt from it. Don't treat this as a permanent guarantee —
  if auth ever starts failing, the PKI guide is the first thing to check — but there's no
  reason to pre-build certificate handling now.
- **PJM Data Miner: confirmed feed behavior (2026-10-13), and it changes the "5-minute"
  story.** Verified directly against `api.pjm.com`, not assumed:
  - **No single feed is both settlement-quality and continuously updating.** `rt_hrl_lmps`
    (hourly) and `rt_fivemin_hrl_lmps` (5-minute granularity, verified/settlement-quality)
    both have `postingFrequency: "Daily On Business Days"` — new data lands once a day, not
    every 5 minutes, regardless of the row interval. `rt_unverified_fivemin_lmps` is the one
    feed that actually posts `"Every 5 minutes"`, but PJM's own description is explicit that
    it is "not settlement quality... subject to change as part of the Verification process",
    and it's retained only **30 days**.
  - **Recommendation — use both, for different jobs.** Backfill and model training read
    `rt_fivemin_hrl_lmps` (verified, 5-minute granularity, `firstAvailable: 2018-04-01`,
    retained indefinitely — comfortably covers the 2+ year window Section 6 wants, archived
    with reduced query flexibility after 2 years). The live poller additionally polls
    `rt_unverified_fivemin_lmps` for dashboard freshness only, clearly labeled
    "provisional" in the UI, with the next day's verified values reconciling it through the
    same revision-aware upsert `eia_readings` already uses (Section 6) — unverified LMP
    getting corrected the next day is a real, expected revision, not an edge case.
  - **The honest cadence claim, restated:** settlement-quality PJM LMP is near-real-time at
    best (next-business-day for verified data), with a provisional same-day view available
    but explicitly unverified. This is a more precise (and more defensible) version of the
    "polling-to-Kafka at a 5-minute cadence" framing below — the 5-minute number describes
    row granularity, not data freshness, for anything but the unverified feed.
  - **UTC is native, not derived.** Both feeds expose `datetime_beginning_utc` /
    `datetime_ending_utc` columns alongside the `_ept` ones — request UTC directly rather
    than converting from Eastern Prevailing Time at ingest. This removes the DST
    duplicate-hour conversion risk Section 7 otherwise has to handle by hand.
  - **Open (ran into the rate limit before confirming):** the exact zone-identifier strings
    for PECO/PPL/METED/PENELEC/DUQ in the `type=ZONE` / `pnode_name` filter. Filters are
    passed as a JSON array of single-key objects, e.g.
    `filters=[{"datetime_beginning_ept":"30minutesago"},{"type":"ZONE"}]` — confirm the
    zone names with one more small, rate-limit-respecting query before writing
    `pjm_poller/client.py`.
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
  check. **Measure before engineering around it:** k3s, Kafka, Postgres, Prometheus and a
  set of CronJobs may well clear the 20% threshold on 2 OCPUs through genuine work. If they
  don't, prefer real workload (more frequent model scoring, longer Prometheus retention) over
  a synthetic keepalive loop, which is gaming the check rather than using the instance. In
  any case keep the Terraform/redeploy story ready so losing the instance is a non-event.
  If this becomes a real problem, verify current alternatives before relying on them —
  Fly.io and Railway have both substantially curtailed their free offerings since the days
  when they were the standard answer, so treat a ~$5/month small VPS as the realistic
  fallback rather than assuming another free tier is waiting.
- **PJM "real-time" LMP: 5 minutes is the row granularity, not the data freshness** —
  confirmed empirically in the Data Miner entry above, more nuanced than first assumed here.
  Settlement-quality LMP posts once a day; only the explicitly-unverified feed actually
  updates every 5 minutes. "Streaming" means polling-to-Kafka, not a continuous event
  stream, either way — but say which feed and which guarantee in anything public-facing.
- **Oracle gives new instances an ephemeral public IP by default, which changes if the VNIC
  is detached or the instance is recreated** — this would silently break a public link.
  Always Free allows up to 2 **Reserved** Public IPv4 addresses at no cost, as long as one
  stays attached to a running instance. Explicitly create and attach a Reserved Public IP
  during Phase 5 deploy — don't rely on the default ephemeral one.
- **EIA-930 data is revised after publication, and publishes on a lag.** Hourly values are
  restated as EIA reconciles them, and initial figures appear hours after the hour they
  describe — the public tier is near-real-time, not real-time, and the dashboard and README
  must say so plainly (same honesty standard Section 3 already applies to PJM's 5-minute
  cadence). The engineering consequence is larger than it looks: train on revised history
  while serving on unrevised live values and the model sees a different distribution at
  inference than it did in training. That is train/serve skew — a sibling of the leakage
  Section 2 exists to prevent. Handled by the revision policy in Section 6.
- **Always Free ARM (A1) capacity is frequently unavailable.** "Out of host capacity" at
  launch is routine in busy regions and can persist for days — this is the single most
  common way Oracle Always Free fails people. Mitigate by retrying the launch on a loop
  (OCI CLI from a cron) and staying flexible across availability domains. Crucially, **this
  blocks only Phase 5**: Phases 1–4 run on a local k3d/kind cluster, so capacity trouble
  delays deployment without ever blocking development. See "Local fallback" in Section 5.
- **EIA-930 historical depth is confirmed sufficient for a time-based split:** most fields go
  back to July 2015 (sub-regional demand and generation-by-source specifically back to July
  2018) — more than enough history to train on an older window and evaluate on a recent one
  without resorting to a short, thin dataset.

## 4. Data sources

### Public tier (feeds the public dashboard — legally unrestricted, any audience)

- **EIA Open Data API** (`eia.gov/opendata`) — free, instant registration, U.S. federal
  government data (public domain, no copyright, no redistribution restriction, no membership
  tier). Use the **Hourly Electric Grid Monitor (EIA-930)** dataset: hourly demand, net
  generation, and interchange for PJM as a Balancing Authority. This is PJM's whole
  multi-state footprint, not broken into PA-specific zones — that granularity loss is the
  price of this data being safely public.

### Private tier (research/analysis only — never exposed on the public dashboard)

- **PJM Data Miner 2** (`api.pjm.com`, access confirmed live — Section 3/10) — locational
  marginal pricing (LMP) by zone, across three feeds with different tradeoffs: verified
  `rt_fivemin_hrl_lmps` (5-min granularity, posts daily, deep history — backfill/training),
  verified `rt_hrl_lmps` (hourly, posts daily, history to 1998), and
  `rt_unverified_fivemin_lmps` (posts every 5 minutes, not settlement-quality, 30-day
  retention — live dashboard freshness only). Section 3 has the full detail and the
  recommended use of each. Keep its Grafana dashboard authenticated-only, never a public link.
- **PA zones to monitor:** PECO, PPL, METED, PENELEC, and DUQ (Duquesne Light) — these cover
  Pennsylvania within PJM's transmission zone map. Exact `pnode_name`/zone-identifier
  strings for the `type=ZONE` filter are still unconfirmed — ran into the rate limit before
  verifying them live; confirm with one small query before writing `pjm_poller/client.py`.
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
  └───────────────────┘      └───────────────────┘      │ (isolation forest │
                                                          │  on forecast      │
                                                          │  residuals)       │
                                                          └─────────┬─────────┘
                                                                    ▼
  ┌───────────────────────┐  ◀─ reads history ──     ┌───────────────────┐
  │ Forecast CronJob      │                          │ Postgres:         │
  │ (torch, scheduled —   │  ── writes forecasts ▶   │ eia_readings,     │
  │  never a live service)│                          │ eia_forecasts     │
  └───────────────────────┘                          └─────────┬─────────┘
                                                                    ▼
                                                   Grafana "Public" dashboard —
                                                   shared via Grafana's native
                                                   EXTERNALLY SHARED DASHBOARD
                                                   feature (only this dashboard,
                                                   nothing else in the instance)

PRIVATE PIPELINE (research/analysis only — never a public link)
─────────────────────────────────────────────────────────────
  ┌────────────────────┐      ┌────────────────────┐
  │ PJM Data Miner API │      │ Queue / Large Load │
  │ (verified: daily;  │      │ Registry (batch,   │
  │ unverified: 5-min) │      │ cron/K8s CronJob)  │
  └──────────┬─────────┘      └──────────┬─────────┘
             ▼                           ▼
  ┌───────────────────┐      ┌───────────────────────┐
  │ Kafka: pjm.lmp.raw │      │ Postgres:             │
  └─────────┬──────────┘      │ interconnection_queue │
            ▼                 └───────────┬───────────┘
  ┌───────────────────┐                   │
  │ Inference service  │                   │
  │ (sklearn only,     │                   │
  │  no torch)         │                   │
  └─────────┬──────────┘                   │
            ▼                              │
  ┌───────────────────┐◄──────────────────┘
  │ Postgres:          │  join CronJob (monthly,
  │ lmp_readings,      │  zone x month grain)
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

Forecasts are produced by a scheduled CronJob writing predictions to Postgres — not by a
long-running service — so no serving container ever loads PyTorch.

Prometheus scrapes /metrics from both pollers + both inference services, and alerts on
ingest staleness (see Section 7).
```

**Both tiers run on the Oracle VM.** Nothing in this system is permanently hosted on a
personal machine: the VM is always-on, and a laptop being asleep must never create a gap in
collection. Docker Compose (or k3d) reproduces the stack locally for development only.

### Always-on vs scheduled workloads

With 2 OCPUs / 12GB shared by everything, the cheapest memory is memory you don't allocate.
Only these run continuously as Deployments:

- EIA poller, PJM poller (small, mostly idle)
- Two inference services — kept separate so PJM and EIA data never share a serving path,
  but **scikit-learn only**, which keeps each around 150MB instead of ~400MB with torch
- Kafka (single KRaft broker), Postgres, Prometheus, Grafana

Everything else is a **CronJob** that wakes, runs, and exits:

- Forecast generation (writes predictions to Postgres for both tiers)
- Queue / Large Load Registry scraper — the source updates on a disclosure cadence, there is
  nothing to poll continuously
- The monthly zone x month correlation join
- Backfill, when run

Steady state should sit near 5–6GB, leaving genuine headroom rather than running at 65%
committed on a box with no vertical scaling path.

### Local fallback (if the Oracle VM is unavailable)

A1 capacity shortages and instance reclamation are both real (Section 3), so the build must
never depend on the VM existing:

- **Phases 1–4 need no cloud at all.** Docker Compose covers day-to-day development, and a
  local **k3d/kind** cluster validates the actual Kubernetes manifests — meaning Phase 5
  becomes "apply known-good manifests to a different cluster" rather than a first attempt.
- **For demoing without a public IP**, a Cloudflare Tunnel (or Tailscale Funnel) exposes a
  local Grafana over HTTPS on a real hostname. Good for a live interview demo; not a
  substitute for 24/7 hosting, since it's only up while the machine is.
- **For genuine 24/7 if Oracle never comes through**, the honest answer is a ~$5/month VPS,
  not another free tier. The stack is portable by design — k3s manifests plus two API keys.

### Public dashboard: provisional panel sketch

Rough shape, to be refined in Phase 4 once there's real data to look at — recorded here so
the dashboard is designed rather than assembled from whatever queries happen to exist:

1. **Header stat row** — current PJM demand, 24h peak, data freshness ("last EIA reading:
   N hours ago"), anomalies flagged in the last 7 days.
2. **Demand vs forecast, last 7 days** — actual load line with the forecast band behind it;
   flagged intervals marked. This is the project's single money panel.
3. **Forecast residuals** — the series the detector actually scores, with the alert
   threshold drawn in, so a visitor can see *why* something was flagged.
4. **Anomaly log table** — timestamp, magnitude, residual, duration; most recent first.
5. **Generation mix over time** — stacked area, context rather than detection.
6. **Model methodology footer** — plain-language note on the time-based split, the baselines
   it was measured against, and an explicit statement that anomaly labels don't exist.

Panels 1–4 are the story; 5–6 are credibility. Nothing here touches a PJM-sourced table.

### Public access: domain + TLS

A bare Oracle IP doesn't give you clean HTTPS, and a raw `https://1.2.3.4` link looks
unfinished. Plan:

1. Reserve a Oracle Cloud **Reserved Public IP** (see risks above) and attach it to the VM.
2. Register a free subdomain pointed at that IP — a free dynamic-DNS provider (e.g. DuckDNS)
   is the simplest option and takes minutes.
3. k3s ships with Traefik as its default ingress controller — use it (or add cert-manager)
   to terminate TLS automatically via Let's Encrypt against that subdomain.
4. Only route the subdomain to the externally shared dashboard's URL (the specific
   public-tier dashboard) — don't expose the rest of the Grafana instance, Kafka, or Postgres
   through the ingress at all.

## 6. Data & modeling methodology

Decided up front because these choices shape what gets logged from day one, and because
Section 2 commits to an honest write-up rather than an impressive-sounding one.

### Historical backfill

The live pollers alone can't train anything — a model needs years of history before the
first real-time message arrives. Backfill is therefore a first-class part of Phase 1, not
an afterthought.

- Loaders live in `/ingestion/backfill/` and write **the same Postgres tables, through the
  same normalization code, as the live pollers.** Train-time and serve-time data must be
  identical in shape, or the evaluation is measuring the wrong thing.
- Idempotent **and revision-aware**: `ON CONFLICT (source, zone, interval_start) DO UPDATE`
  when the value actually changed, with a `retrieved_at` column recording when each version
  was fetched. `DO NOTHING` would be simpler and wrong — EIA restates published figures, and
  first-write-wins would permanently freeze whichever value happened to arrive first.
  Runnable both as a CLI (`python -m ingestion.backfill --source eia --start 2019-01-01`)
  and as a K8s Job.
- **The live poller re-pulls a rolling 72-hour window every cycle**, not just the newest
  hour. This absorbs both the publication lag and the revisions in one mechanism, and means
  the live path and the backfill path converge on identical values rather than drifting
  apart. Train/serve skew is prevented here, at ingest — not patched later in the model.
- **Cadences:** EIA hourly (the data is hourly; polling faster just re-reads the same rows),
  PJM every 5 minutes to match its refresh, queue/registry on a daily check that no-ops
  unless the source document changed.
- **EIA:** pull PJM BA hourly demand, net generation, and interchange from **2019-01-01**
  onward (sub-regional/by-source data starts July 2018, so 2019 is a clean full-year
  boundary). That is roughly 60k hourly rows — trivial for Postgres. Paginate around the
  API's 5,000-row response cap.
- **PJM (once provisioned):** 5-minute RT LMP for the five PA zones, **2+ years** — on the
  order of a million rows. **Measure the per-request page size before assuming a duration:**
  Data Miner serves paged date-range downloads, so at a large page size this is a few dozen
  requests (minutes), and at a small one the 6 req/min non-member ceiling turns it into an
  overnight job. Check this in Phase 1, run it once, and don't re-pull casually either way.

### Train/validation/test split

- Strictly time-ordered, never shuffled. Scalers, thresholds, and contamination parameters
  are fit on **train only** — leakage sneaks in through the scaler far more often than
  through the model itself.
- Public (EIA) tier, concretely: **train 2019-01-01 → 2025-06-30, validation 2025-07-01 →
  2025-12-31, test 2026-01-01 → freeze date.** The test window is touched once, at the end.
- These dates live as frozen constants in `/model/splits.py` — not as notebook variables
  that quietly drift between runs.

### Feature design: what actually gets scored

The most consequential modeling decision in the project, and the easiest one to get
silently wrong.

- **Score forecast residuals, not raw levels.** An isolation forest fed raw demand will
  flag every July afternoon and every January cold snap — correctly, in that those hours
  are statistically extreme, and uselessly, in that everyone already knows summer is hot.
  Scoring `actual - forecast` instead makes an anomaly mean *"the grid did something the
  model did not expect"*, which is the actual story and the thing a data-center-driven
  deviation would show up in.
- This also makes the forecaster load-bearing rather than decorative: it earns its place by
  defining the baseline the detector measures against, which is a cleaner justification
  than "the architecture called for an LSTM".
- **Features:** residual plus calendar context (hour-of-day, day-of-week, holiday flag) and
  short-window rate of change. Deliberately not weather, at least at first — weather
  explains most load variance, so including it makes the model better at forecasting and
  worse at *surfacing* the unexplained behaviour this project is looking for. Revisit
  during the weather-normalization work in the correlation layer.
- **Missing data has an explicit policy, decided before training.** EIA-930 has gaps and
  nulls; untreated, a gap looks exactly like the flatline pattern the synthetic-injection
  harness tests for, so the evaluation would end up scoring data-quality artifacts and
  calling them anomalies. Rule: forward-fill gaps of 1–2 hours, mark longer gaps as
  `quality = 'missing'` and exclude them from both training and scoring, and surface
  gap counts on the dashboard rather than hiding them.

### Evaluating an unsupervised detector (the honest version)

There are no ground-truth anomaly labels for this data. That constraint is stated plainly
in the README rather than papered over with a precision/recall number that doesn't exist.

- **The forecast model carries the quantitative claim.** MAE / MAPE / RMSE on the held-out
  test window, reported against two baselines: seasonal-naive (same hour, previous week)
  and a day-of-week × hour-of-day profile regression. **Both baseline numbers get published
  alongside the model's.** If the LSTM doesn't beat them, the README says so and the
  baseline stays in production — that is a better engineering story than a model that wins
  on narrative only.
- **The anomaly detector gets a two-part evaluation:**
  1. *Synthetic injection (quantitative).* Inject labeled perturbations into held-out data
     at known timestamps — step changes, spikes, flatlines (stuck-sensor), and abnormal
     ramps — then report recall at a fixed alert budget (at most 1% of intervals flagged).
     This measures sensitivity against known-bad signals without pretending the real data
     is labeled.
  2. *Event correspondence (qualitative, labeled as such).* Do flagged intervals line up
     with known real events — heat waves, winter storms, PJM cold-weather alerts and
     emergency procedures? Presented as a sanity check, never as a metric.
- Operating threshold is chosen on **validation**, frozen, then reported on test.

### Retraining, drift, and cold start

There's a real tension here, and naming it is better than silently picking a side:

- **Retrain the detector too often and it erases the project's own thesis.** If the training
  window keeps sliding forward, the model gradually learns that the new, higher,
  data-center-inflated baseline is perfectly normal — normalizing precisely the trend the
  project exists to highlight. Never retrain, and it drifts until everything looks anomalous.
- **Resolution: freeze the detector, schedule the forecaster.** The anomaly detector keeps a
  fixed training window so "anomalous" stays anchored to a stable historical definition. The
  forecaster retrains monthly so predictions track reality. Each retrain is versioned and its
  test-window metrics recorded, so regressions are visible rather than inferred.
- That tension is worth a paragraph in the README on its own — it's a more interesting
  modeling discussion than the architecture diagram.
- **Cold start:** the forecaster needs a lookback window to predict anything, so on boot the
  service queries Postgres for the trailing window rather than waiting to accumulate it from
  Kafka. A restarted pod must be useful immediately, not hours later.

### Correlation layer: grain and claim discipline

Queue and Large Load Registry data arrives as periodic snapshots; LMP arrives every five
minutes. The join can only live at the coarse end of that gap.

- **Grain: one row per PA zone per month.** `zone_stress_vs_dc` holds `(zone, month,
  anomaly_count, hours_above_price_threshold, mean_lmp, peak_load,
  queued_large_load_mw_cumulative, new_large_load_mw_this_period)`.
- `interconnection_queue` is stored as **slowly-changing snapshots** —
  `(snapshot_date, project_id, zone, mw, status)` — never overwritten in place. Without
  point-in-time reconstruction you can't say what the queue looked like back when a given
  month's stress actually occurred.
- **Claim discipline.** This is observational, with 5 zones and a few dozen months; queued
  MW is not energized load; weather, fuel prices, and transmission outages are obvious
  confounders. It ships as a described correlation with the confounders named in the
  README — never as a causal claim. Weather-normalizing load against NOAA HDD/CDD before
  making any load-growth statement is the stretch version of doing this properly.
- **The public tier has no correlation panels at all.** EIA-930 is BA-level with no PA zone
  breakdown, so the correlation story is structurally private-tier-only. That is a data
  limitation, not only a licensing one.

## 7. Engineering conventions

Defaults chosen to fit 2 OCPUs / 12GB of ARM — change them if there's a reason, but each
one is here because the alternative costs memory, headroom, or correctness.

- **Time is UTC, always.** Every timestamp is `timestamptz` stored in UTC, using an
  interval-*beginning* convention. PJM's Eastern Prevailing Time (and the annual duplicate
  DST hour) is converted at ingest; naive timestamps never reach the database. Grafana does
  the display-side conversion to `America/New_York`. Retrofitting this later is miserable.
- **Training happens off-cluster.** Models are trained locally on x86 and the artifacts are
  versioned. The Oracle VM serves inference; it does not fit models. 12GB shared with Kafka
  and Postgres is not a training box.
- **Artifacts are handled differently per tier, because of the Section 2 publication
  policy.** A model trained on PJM data is PJM-derived material, so it cannot ride along in
  a public image or a public release:
  - *Public (EIA) tier* — artifact baked into the image, published to public GHCR, attached
    to git releases. Federal public-domain input, nothing to protect.
  - *Private (PJM) tier* — artifact **never committed and never baked into a public image**.
    It lives on a PVC on the VM (and locally for development), mounted at runtime; if baking
    it in is ever more convenient, that image goes to a *private* GHCR package. The
    distinction is deliberate: publishing a model trained on PJM data publishes PJM-derived
    material just as surely as committing a CSV would.
- **PyTorch, not TensorFlow** — the arm64 wheel story is dramatically cleaner — plus
  scikit-learn for the isolation forest. The LSTM only ships if it beats the baselines.
- **Images are `linux/arm64`** (Ampere A1), built with `docker buildx`, Python slim base,
  no conda. Published to **GHCR** — public for the EIA tier, private for any image carrying
  a PJM-trained artifact.
- **CI/CD is pull-based** (stretch goal 1). GitHub Actions lints, tests, and pushes to
  GHCR; the cluster pulls. The k3s API server is never exposed to the internet — admin
  access is SSH-only — so there is no inbound cluster credential for CI to hold or leak.
- **Secrets are never committed.** Local dev reads a gitignored `.env` alongside a
  committed `.env.example`; the cluster uses Secrets created out-of-band with `kubectl`,
  referenced by name from the manifests. If PKI client certs turn out to be required,
  they're mounted as files from a Secret, not stuffed into env vars. SOPS/sealed-secrets
  only if the manifests ever need to be fully self-contained.
- **Postgres is the system of record; Kafka is transport.** Kafka retention stays short
  (24h or a small size cap) so it can't eat the volume. No backup requirement — every row
  is re-derivable by re-running backfill against both APIs, and public-tier model artifacts
  live in git releases (private-tier artifacts are re-trainable locally from Data Miner, per
  the artifact rule above).
- **Resource limits on everything.** Single Kafka broker in KRaft mode with a capped heap
  (512MB–1GB), Prometheus at 15d retention and a 30s scrape interval, explicit small
  requests/limits on Grafana and Postgres. Target: roughly 2GB headroom free at steady
  state.
- **Config is env-var driven via pydantic-settings**, so Compose and k8s run the same code
  path with different values.
- **Tests are pytest, with API clients exercised against recorded fixtures** — CI makes no
  live API calls (the 6 req/min PJM limit alone makes that a bad idea). CI runs ruff +
  pytest + an arm64 image build on every push.
- **No PyTorch in any serving container.** Forecasts are generated by a scheduled CronJob
  and written to Postgres; the inference services carry scikit-learn only. This is both a
  memory decision (~150MB vs ~400MB per replica, twice over) and a simpler one — Grafana
  reads predictions from Postgres regardless, so a live torch process was never on the read
  path to begin with.
- **Normalization lives in `/common`, not in the Kafka consumer.** There are two write paths
  into the same tables — live (poller → Kafka → consumer → Postgres) and bulk (backfill →
  Postgres) — and the "train and serve see identical data" guarantee in Section 6 only holds
  if both import the same transformation code. Putting it in the consumer quietly breaks
  that the first time backfill runs.
- **Migrations are plain numbered SQL files** applied by an init job — not Alembic. The
  schema is a handful of tables; a migration framework is a dependency and a failure mode
  this project doesn't need to buy.
- **Dashboards are code.** Grafana dashboards are provisioned from JSON committed to the
  repo, never clicked together in the UI. Losing the VM should cost an afternoon of
  redeployment, not the project's entire visible output. (PJM dashboard JSON contains panel
  definitions and queries, not data — but check it for embedded sample values before
  committing, per the Section 2 publication policy.)
- **The pipeline must alert on its own death.** A silently dead poller is the single most
  likely real failure, and a dashboard of stale data is visually indistinguishable from a
  quiet grid. Minimum metrics from every service: time since last successful ingest (per
  source), API error rate, Kafka consumer lag, inference latency, and anomalies flagged per
  hour. **One Prometheus alert on ingest staleness is worth more than all the others
  combined** — if only one alert ever gets written, write that one.
- **Logs are structured JSON to stdout**, read via `kubectl logs`. No Loki, no log
  aggregation stack — it would cost ~500MB to solve a problem this project doesn't have yet.

## 8. Proposed repo structure

```
/common              shared config (pydantic-settings), Kafka + Postgres clients,
                     logging, Prometheus metric helpers — used by every service
/ingestion
  eia_poller/        public-tier poller (EIA-930, hourly)
  pjm_poller/        private-tier poller (PJM Data Miner, 5-min)
  queue_scraper/     interconnection/Large Load Registry batch job
  backfill/          idempotent historical loaders — same tables, same normalization
                     code as the live pollers (Section 6)
/inference           FastAPI service(s), model loading, serving (both tiers)
/model               training scripts, splits.py (frozen split dates), evaluation
                     (baselines + synthetic-injection harness), saved artifacts
/alerting            stretch: Slack/email notifier (private tier only)
/infra
  docker-compose.yml   local dev stack
  /k8s               plain manifests (or Helm charts) for every service above,
                     including Grafana provisioning: the public-tier dashboard
                     (EIA-only, externally shared) and the private one (auth-only)
  /terraform          stretch: Oracle VM + k3s bootstrap
/tests               pytest; API clients run against recorded fixtures, never live
                     calls in CI
/notebooks           exploration only — nothing here is on the serving path
/.github/workflows/ci.yml   ruff + pytest + arm64 image build on every push
README.md             documents the public/private data split explicitly for anyone
                      reading the repo (including why), plus the model methodology
                      write-up (what was validated, what wasn't)
.env.example          every env var the stack reads; the real .env is gitignored
```

## 9. Build phases

1. **Ingestion + storage** — EIA poller (public tier) first since it's unblocked and
   zero-risk, plus the EIA **backfill** to 2019 in the same pass (the model has nothing to
   train on without it); PJM poller and its 2-year backfill once non-member access is
   provisioned; queue scraper/Large Load Registry once its access mechanism is confirmed.
   Postgres schema for all three, UTC `timestamptz` throughout. Confirm the PKI auth
   question and the Large Load Registry data source here first — don't proceed past this
   phase on unverified assumptions.
2. **Model** — baselines first (seasonal-naive, day×hour profile), then isolation forest
   and optionally an LSTM forecast per tier, on the frozen time-based split from Section 6.
   Build the synthetic-injection harness here too — it is the only quantitative handle on
   the detector. Write up the methodology honestly: what was validated, what wasn't, and
   the baseline numbers next to the model's.
3. **Pipeline wiring** — Kafka producers/consumers for both tiers, FastAPI inference
   service(s), Docker Compose local stack end-to-end.
4. **Observability** — Prometheus + two Grafana dashboards: the public one (EIA-only data,
   shared via Grafana's Externally Shared Dashboards feature) and the private one (PJM zone
   data + data-center correlation, authenticated access only). Double-check the public
   dashboard genuinely has zero PJM-sourced panels before enabling external sharing.
5. **Deploy** — write the Kubernetes manifests and validate them on a **local k3d/kind
   cluster first**, so the Oracle deploy is "apply known-good manifests" rather than a first
   attempt (and so an A1 capacity shortage delays nothing). Then Oracle Cloud VM + k3s, live
   24/7. Reserve the Oracle Public IP, point a free subdomain at it, wire up Traefik/cert-manager for Let's Encrypt
   TLS (see "Public access: domain + TLS" above) before calling the public link done.
6. **Stretch** (in priority order) — CI/CD auto-deploy, Slack/email alerting, Terraform IaC.

## 10. Steps to complete before building starts

These are the only external dependencies — everything else (Kafka, Postgres, Grafana, k3s,
Docker, GitHub Actions) is self-installed later and needs no advance signup.

1. ✅ **EIA API key** — obtained and saved securely (not in the repo).
2. ✅ **PJM Tools account created** — via `accountmanager.pjm.com` / `apiportal.pjm.com`.
   This alone does not grant API access; the provisioning email in step 3 is what does.
3. ✅ **Non-member provisioning email sent** to `accountmanager@pjm.com`, and **access
   confirmed live** (2026-10-13) — a plain `Ocp-Apim-Subscription-Key` successfully
   authenticates against real Data Miner 2 endpoints. The private tier is unblocked.
4. ✅ **PKI-certificate auth checked** — not required. The plain subscription key above
   authenticated without one, confirmed live against `api.pjm.com` (Section 3 has the
   detail). Revisit only if auth starts failing later.
5. **Oracle Cloud account** — in progress. Once the VM exists: reserve a Public IPv4 address
   (Always Free allows 2 at no cost) and attach it, rather than leaving the default ephemeral
   IP in place.
6. ✅ **GitHub repo created** — `github.com/aaaaaron29/pa-grid-monitor`, architecture doc
   pushed.
7. **Register a free subdomain** (e.g. via DuckDNS) pointed at the Oracle VM's eventual
   reserved IP — needed for the TLS/public-access plan in Section 5. Can be done anytime
   before Phase 5 deploy, no rush.

The only remaining external dependency is step 5 (Oracle Cloud account, needed for Phase 5
deploy only). PJM access is confirmed and live, so the private tier is unblocked too —
remaining PJM work is the zone-identifier confirmation and feed-strategy implementation
noted in Section 3/4, not an access/provisioning wait.
