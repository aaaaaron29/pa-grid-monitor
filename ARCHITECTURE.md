# PJM Grid Watch: Architecture

Repo: `pa-grid-monitor` (github.com/aaaaaron29/pa-grid-monitor).

## 1. What this project is

A near-real-time, actually-deployed grid-monitoring system for electricity price and load
anomalies on the PJM grid, with a correlation layer tying anomaly activity to data-center-
driven load growth in Pennsylvania (a live, current story given PJM's ongoing AI/data-center
load surge and the new FERC-approved Large Load Registry).

The goal is genuine end-to-end infrastructure (Kafka, Kubernetes, Prometheus/Grafana, CI/CD),
not a toy pipeline, paired with a deliberately rigorous ML methodology: a time-based
train/test split, since naive random splits on time-series/grid data are a well-known leakage
risk (information from the future leaking into training).

"Near-real-time" is deliberate wording: EIA-930 publishes on a multi-hour lag and PJM
refreshes every five minutes, so this is frequent polling, not a continuous event stream.
The project claims what it actually does. See Section 3.

## 2. Scope decisions (locked in during planning; don't relitigate these mid-build)

- **Stack:** Python only for the data/ML pipeline (ingestion, Kafka, the trained models).
  Deliberately not adding another language there: that part already stacks Kafka +
  Kubernetes + a trained model + Prometheus/Grafana; a new language on top of it risks
  becoming unfocused. **Amended 2026-10-15:** this lock doesn't extend to the presentation
  layer. The custom frontend (Section 9, item 7) is TypeScript/Next.js, a deliberate,
  acknowledged exception, not a quiet reversal -- a read-only web frontend is a different
  problem than the pipeline this rule was written for, and Python has no equivalent
  ecosystem for it.
- **Model depth:** a real trained ML model (isolation forest for anomaly scoring, LSTM or
  similar for load forecasting), not just a rolling z-score. **The detector scores forecast
  residuals, not raw demand levels** (see Section 6, "Feature design"); this is the decision
  that makes an anomaly mean "the grid did something unexpected" rather than "it was hot". Must use a **time-based**
  train/test split (train on older data, evaluate on most recent) to avoid lookahead/leakage.
  Document the methodology in the README, not just the code. Keep any description of the
  model honest: don't overclaim rigor beyond what was actually validated.
- **Interconnection-queue correlation was planned as a core feature, not a stretch goal**:
  joining data-center siting/large-load queue data with zone-level grid stress. **Confirmed
  deferred (2026-10-14): there is no public data source to join against yet.** See Section 3
  for the real findings; this is not an assumption. The schema (`interconnection_queue` as
  slowly-changing snapshots, Section 6) is still designed for it, so adding it back once a
  real source exists is a bolt-on, not a redesign. Phases 4 and 5 proceed on EIA + PJM zone
  data only.
- **Visualization:** Prometheus + Grafana (self-hosted on the same cluster), not Streamlit.
- **Deployment:** real Kubernetes (k3s), not just Docker Compose. Compose is for local dev only.
- **Hosting:** Oracle Cloud "Always Free" tier VM, chosen because it's the only realistic
  free option that can run a real, persistent, stateful stack (Kafka + Postgres + k3s)
  24/7. Vercel was considered and rejected (serverless/static only, can't run long-running
  Kafka brokers or consumers).
- **Public/private data split (locked after legal check, see Section 3):** the live,
  publicly-hostable, shareable-with-anyone site runs entirely on **EIA data** (public domain,
  zero redistribution restriction, any audience size). **PJM Data Miner's zone-level LMP data
  stays a private research/analysis layer**, used for your own model development and the
  PA-zone-specific story, shown live via screen-share/interview, never on the public
  dashboard. Don't blur this line mid-build; it's the difference between compliant and not.
- **Publication policy: the public GitHub repo counts as publishing.** Anything committed
  is world-readable, which is the same act Section 3's restriction prohibits, so "it's only
  in the README" is not a safe harbour. The rule: **no raw PJM values, no sample rows, no
  LMP screenshots, and no PJM-trained model artifacts in the repo.** What *is* publishable
  is the work that isn't the data: code, schema, methodology, and aggregate findings
  stated in prose ("PECO showed N anomalous intervals in Q1"). The private dashboard is
  demonstrated live, never captured into the repo. The goal isn't to obscure the data, it's
  to not republish it; derived aggregates and methodology are genuinely a different thing,
  and that distinction holds up under scrutiny in a way obfuscation wouldn't.
- **Timeline:** open-ended; prioritize depth and quality over speed.
- **Stretch goals (in priority order, do core pipeline first):**
  1. CI/CD auto-deploy on push (GitHub Actions → build → push to live Oracle k3s cluster)
  2. Slack/email alerting on detected anomalies
  3. Terraform/IaC for the Oracle VM + k3s bootstrap

## 3. Known risks to resolve early (don't assume; verify in Phase 1)

- **Non-member API registration requires a manual email step, not instant self-service.**
  Per PJM's own Data Miner API Guide: after creating a PJM Tools account at
  `accountmanager.pjm.com` / `apiportal.pjm.com`, non-members must separately email
  `accountmanager@pjm.com` with the exact statement *"I confirm that the PJM Data will be
  used for internal business purposes only,"* including your Account Manager user id and the
  email used to subscribe. PJM then manually provisions non-member API access; expect a
  human-review turnaround delay. **Status: confirmed live (2026-10-13).** A real
  `Ocp-Apim-Subscription-Key` now authenticates against `api.pjm.com` (verified directly:
  HTTP 200 against `rt_hrl_lmps/metadata` and others, real data returned). The private tier
  is unblocked; see the new "PJM Data Miner: confirmed feed behavior" entry below for what
  that access actually looks like.
- **Grafana's public-sharing feature is confirmed available in OSS, no extra licensing
  needed.** It's officially called "Externally Shared Dashboards" (formerly "Public
  Dashboards") as of recent Grafana versions, enabled by default, and works per-dashboard,
  exactly the isolation this design needs. Requires Admin or the `dashboards.public:write`
  permission to enable on a given dashboard. Note the mechanism: a shared dashboard re-runs
  its stored queries against the live datasource on each public view, so make certain the
  "Public" dashboard's queries only ever touch the `eia_readings` table; never point a
  public-shared panel at anything PJM-sourced.
- **Non-member redistribution restriction (confirmed from PJM's actual Data Miner 2 Terms of
  Use, Section 1):** "Members may republish data, however non-members are specifically
  prohibited from republishing data." Without an Associate Membership (a paid, company-level
  tier, a company-level commitment not worth taking on here), **any PJM-fed dashboard
  cannot be a fully public, open URL**, that likely counts as republishing. Internal/personal use, local
  development, and screen-shared/recorded demos are fine. **Scope: this binds PJM-sourced
  data only.** It is why the private dashboard stays behind Grafana auth and is never
  externally shared; it is *not* a reason to gate the public tier, which is EIA-only
  (U.S. federal public domain) and is meant to be an open, linkable URL.
- **Non-member rate limit is 6 requests/minute** (members get 600/min), per the same Terms of
  Use (Section 2), **and empirically confirmed**: testing the live key tripped a 429 after
  ~6 metadata/data calls inside a couple of minutes. It's real and it bites fast; back off
  aggressively, especially while exploring feeds by hand. Irrelevant at a 5-minute polling
  cadence for the poller itself; it matters for the historical backfill, where the
  per-request page size determines whether that job takes minutes or hours (Section 6).
- **Use the `gridstatus` Python library (`pip install gridstatus`) instead of hand-rolling
  PJM API calls.** It's an actively maintained open-source wrapper that already handles PJM
  LMP, load, and, notably, interconnection-queue data, which may remove most of the custom
  queue-scraper work planned in Phase 1. It expects your key as the `PJM_API_KEY` env var.
  Check its current PJM module first in Phase 1 before building anything custom.
- **PJM API auth: confirmed a plain subscription key is still sufficient (2026-10-13).** A
  bare `Ocp-Apim-Subscription-Key` header authenticated successfully against multiple live
  Data Miner 2 endpoints; no PKI client certificate was required despite PJM's Q3 2026
  rollout target for that requirement. Either the rollout hasn't reached non-member API-key
  auth, or this key predates/is exempt from it. Don't treat this as a permanent guarantee:
  if auth ever starts failing, the PKI guide is the first thing to check, but there's no
  reason to pre-build certificate handling now.
- **PJM Data Miner: confirmed feed behavior (2026-10-13), and it changes the "5-minute"
  story.** Verified directly against `api.pjm.com`, not assumed:
  - **No single feed is both settlement-quality and continuously updating.** `rt_hrl_lmps`
    (hourly) and `rt_fivemin_hrl_lmps` (5-minute granularity, verified/settlement-quality)
    both have `postingFrequency: "Daily On Business Days"`: new data lands once a day, not
    every 5 minutes, regardless of the row interval. `rt_unverified_fivemin_lmps` is the one
    feed that actually posts `"Every 5 minutes"`, but PJM's own description is explicit that
    it is "not settlement quality... subject to change as part of the Verification process",
    and it's retained only **30 days**.
  - **Recommendation: use both, for different jobs.** Backfill and model training read
    `rt_fivemin_hrl_lmps` (verified, 5-minute granularity, `firstAvailable: 2018-04-01`,
    retained indefinitely, comfortably covering the 2+ year window Section 6 wants, archived
    with reduced query flexibility after 2 years). The live poller additionally polls
    `rt_unverified_fivemin_lmps` for dashboard freshness only, clearly labeled
    "provisional" in the UI, with the next day's verified values reconciling it through the
    same revision-aware upsert `eia_readings` already uses (Section 6); unverified LMP
    getting corrected the next day is a real, expected revision, not an edge case.
  - **The honest cadence claim, restated:** settlement-quality PJM LMP is near-real-time at
    best (next-business-day for verified data), with a provisional same-day view available
    but explicitly unverified. This is a more precise (and more defensible) version of the
    "polling-to-Kafka at a 5-minute cadence" framing below: the 5-minute number describes
    row granularity, not data freshness, for anything but the unverified feed.
  - **UTC is native, not derived.** Both feeds expose `datetime_beginning_utc` /
    `datetime_ending_utc` columns alongside the `_ept` ones; request UTC directly rather
    than converting from Eastern Prevailing Time at ingest. This removes the DST
    duplicate-hour conversion risk Section 7 otherwise has to handle by hand.
  - **Zone pnode_ids confirmed (2026-10-13).** `pnode_name` and `type` are not
    server-filterable on this feed (their metadata has `enableFiltering: false`); only
    `pnode_id` is. Pulled an unfiltered interval and matched by name to get stable IDs:
    PECO 51297, PPL 51299, METED 51296, PENELEC 51300, DUQ 37737283. The query itself is a
    POST to the feed's base URL (not a GET with a `filters` querystring, which this feed
    rejects) with a JSON body: `{"rowCount": N, "startRow": 1, "filters":
    [{"datetime_beginning_ept": "5minutesago"}, {"pnode_id": 51297}], "sort":
    "datetime_beginning_ept", "order": 1}`, one `pnode_id` filter per zone or omitted
    entirely to pull all five by filtering client-side.
- **The Large Load Registry (data-center interconnection transparency) was only approved by
  FERC on 2026-10-09**, days before this doc was written. The actual public data access
  mechanism (API vs. CSV export vs. committee PDF disclosures) may not be fully operational
  yet. Budget real investigation time in Phase 1 to find the actual current data source;
  don't assume a clean API exists. Fallback: PJM's planning-committee queue documents
  (CIFP-LLA package materials, board disclosure PDFs) are public but are periodic
  PDFs/spreadsheets, not a live feed; treat queue ingestion as **batch**, not streaming,
  regardless of which source wins.
  - **Investigated for real (2026-10-14), not assumed, and confirmed deferred.** The
    registry's approved provisions took effect 2026-10-12, one to two days before this
    check. Public access will be **aggregated data only**, under PJM's existing
    confidentiality protections, so even once live it will not be the rich per-facility
    dataset this doc's schema was originally imagining. More importantly: PJM's own
    compliance filing describing the actual implementation mechanism is due within 30 days
    of the FERC order, around 2026-11-08 at the earliest. There is nothing to build against
    yet; this is not a missing-API-key problem, it is a does-not-exist-yet problem.
  - **`gridstatus`'s existing `get_interconnection_queue()` for PJM is a different, older
    dataset and does not substitute for this.** That is the long-standing *generator*
    interconnection queue (new power plants/storage requesting to connect), not the
    brand-new *large-load* registry (new large consumers like data centers). Same-sounding
    name, unrelated dataset; do not wire it up expecting it to answer this project's
    correlation question.
  - **Decision: defer the correlation layer rather than build toward an undefined target.**
    Phases 4 and 5 proceed on EIA + PJM zone data only. Revisit after PJM's compliance
    filing actually defines an access mechanism, no earlier than 2026-11-08.
- **Oracle's Always Free compute was cut again, confirmed live 2026-10-14 during actual
  instance creation: 1 OCPU / 6GB RAM total** (ARM Ampere A1), not the 2/12 this doc
  previously documented from July 2026, itself already down from the historical 4/24. The
  instance-creation form offered no adjustable OCPU/memory fields beyond that cap. This is
  genuinely tight for the full stack (Postgres, Kafka, four ingestion services, both
  inference services, Prometheus, Grafana, all on 6GB) and will likely need real K8s
  resource requests/limits tuned per pod before the Oracle deploy, not just "keep images
  small" as previously assumed. Revisit `infra/k8s/`'s manifests for this before applying
  them to the real VM; the kind-based CI verification doesn't catch this, since GitHub's
  runners have far more memory available than the real target.
- **Oracle reclaims idle Always Free instances** if CPU, network, and memory utilization are
  all under 20% for 95% of a rolling 7-day window. A pipeline that just polls an API every
  5 minutes and idles otherwise is at real risk of looking "idle" to Oracle's reclamation
  check. **Measure before engineering around it:** k3s, Kafka, Postgres, Prometheus and a
  set of CronJobs may well clear the 20% threshold on 2 OCPUs through genuine work. If they
  don't, prefer real workload (more frequent model scoring, longer Prometheus retention) over
  a synthetic keepalive loop, which is gaming the check rather than using the instance. In
  any case keep the Terraform/redeploy story ready so losing the instance is a non-event.
  If this becomes a real problem, verify current alternatives before relying on them:
  Fly.io and Railway have both substantially curtailed their free offerings since the days
  when they were the standard answer, so treat a ~$5/month small VPS as the realistic
  fallback rather than assuming another free tier is waiting.
- **PJM "real-time" LMP: 5 minutes is the row granularity, not the data freshness**.
  Confirmed empirically in the Data Miner entry above, more nuanced than first assumed here.
  Settlement-quality LMP posts once a day; only the explicitly-unverified feed actually
  updates every 5 minutes. "Streaming" means polling-to-Kafka, not a continuous event
  stream, either way, but say which feed and which guarantee in anything public-facing.
- **Oracle gives new instances an ephemeral public IP by default, which changes if the VNIC
  is detached or the instance is recreated**. This would silently break a public link.
  Always Free allows up to 2 **Reserved** Public IPv4 addresses at no cost, as long as one
  stays attached to a running instance. Explicitly create and attach a Reserved Public IP
  during Phase 5 deploy; don't rely on the default ephemeral one.
- **EIA-930 data is revised after publication, and publishes on a lag.** Hourly values are
  restated as EIA reconciles them, and initial figures appear hours after the hour they
  describe. The public tier is near-real-time, not real-time, and the dashboard and README
  must say so plainly (same honesty standard Section 3 already applies to PJM's 5-minute
  cadence). The engineering consequence is larger than it looks: train on revised history
  while serving on unrevised live values and the model sees a different distribution at
  inference than it did in training. That is train/serve skew, a sibling of the leakage
  Section 2 exists to prevent. Handled by the revision policy in Section 6.
- **Always Free ARM (A1) capacity is frequently unavailable.** "Out of host capacity" at
  launch is routine in busy regions and can persist for days. This is the single most
  common way Oracle Always Free fails people. Mitigate by retrying the launch on a loop
  (OCI CLI from a cron) and staying flexible across availability domains. Crucially, **this
  blocks only Phase 5**: Phases 1–4 run on a local `kind` cluster, so capacity trouble
  delays deployment without ever blocking development. See "Local fallback" in Section 5.
- **EIA-930 historical depth is confirmed sufficient for a time-based split:** most fields go
  back to July 2015 (sub-regional demand and generation-by-source specifically back to July
  2018), more than enough history to train on an older window and evaluate on a recent one
  without resorting to a short, thin dataset.

## 4. Data sources

### Public tier (feeds the public dashboard; legally unrestricted, any audience)

- **EIA Open Data API** (`eia.gov/opendata`): free, instant registration, U.S. federal
  government data (public domain, no copyright, no redistribution restriction, no membership
  tier). Use the **Hourly Electric Grid Monitor (EIA-930)** dataset: hourly demand, net
  generation, and interchange for PJM as a Balancing Authority. This is PJM's whole
  multi-state footprint, not broken into PA-specific zones; that granularity loss is the
  price of this data being safely public.

### Private tier (research/analysis only; never exposed on the public dashboard)

- **PJM Data Miner 2** (`api.pjm.com`, access confirmed live, Section 3/10): locational
  marginal pricing (LMP) by zone, across three feeds with different tradeoffs: verified
  `rt_fivemin_hrl_lmps` (5-min granularity, posts daily, deep history, used for backfill/training),
  verified `rt_hrl_lmps` (hourly, posts daily, history to 1998), and
  `rt_unverified_fivemin_lmps` (posts every 5 minutes, not settlement-quality, 30-day
  retention, used for live dashboard freshness only). Section 3 has the full detail and the
  recommended use of each. Keep its Grafana dashboard authenticated-only, never a public link.
- **PA zones to monitor:** PECO, PPL, METED, PENELEC, and DUQ (Duquesne Light): these cover
  Pennsylvania within PJM's transmission zone map. Confirmed `pnode_id` values (Section 3):
  PECO 51297, PPL 51299, METED 51296, PENELEC 51300, DUQ 37737283.
- **Data-center / large-load interconnection data**: source TBD at build time. Start with
  the new FERC-approved Large Load Registry (a public regulatory transparency record, not
  Data Miner Tool output, a different legal basis, so not obviously bound by Data Miner's
  Terms of Use) and PJM's openly-posted planning-committee disclosure PDFs (posted directly
  on pjm.com, not gated behind the Data Miner Tool). Confirm actual access mechanism in
  Phase 1; don't assume a clean API exists yet, this was only approved 2026-10-09.

## 5. System architecture

Two parallel pipelines share the same Kafka/Postgres/Grafana infra, but stay data-isolated
because only one of them is legally safe to expose publicly.

```
PUBLIC PIPELINE (safe to expose: powers the public dashboard)
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
  │ (torch, scheduled -   │  ── writes forecasts ▶   │ eia_readings,     │
  │  never a live service)│                          │ eia_forecasts     │
  └───────────────────────┘                          └─────────┬─────────┘
                                                                    ▼
                                                   Grafana "Public" dashboard,
                                                   shared via Grafana's native
                                                   EXTERNALLY SHARED DASHBOARD
                                                   feature (only this dashboard,
                                                   nothing else in the instance)

PRIVATE PIPELINE (research/analysis only; never a public link)
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
  Grafana "Private" dashboard: normal authenticated Grafana login only,
  no public dashboard sharing enabled. Also feeds:
            │
            ▼
  ┌───────────────────┐      ┌───────────────────────┐
  │ Kafka:             │─────▶│ Alerting service       │
  │ pjm.lmp.anomalies  │      │ (stretch: Slack/email) │
  └───────────────────┘      └───────────────────────┘

Forecasts are produced by a scheduled CronJob writing predictions to Postgres, not by a
long-running service, so no serving container ever loads PyTorch.

Prometheus scrapes /metrics from both pollers + both inference services, and alerts on
ingest staleness (see Section 7).
```

**Both tiers run on one always-on server.** Nothing in this system is permanently hosted on a
personal machine: the server is always-on, and a laptop being asleep must never create a gap in
collection. Docker Compose reproduces the stack locally for development only. The server is
now a rented VPS rather than the Oracle VM this section was written for; see "VPS deployment"
in Section 9.

### Always-on vs scheduled workloads

With 2 OCPUs / 12GB shared by everything, the cheapest memory is memory you don't allocate.
Only these run continuously as Deployments:

- EIA poller, PJM poller (small, mostly idle)
- Two inference services, kept separate so PJM and EIA data never share a serving path,
  but **scikit-learn only**, which keeps each around 150MB instead of ~400MB with torch
- Kafka (single KRaft broker), Postgres, Prometheus, Grafana

Everything else is a **CronJob** that wakes, runs, and exits:

- Forecast generation (writes predictions to Postgres for both tiers)
- Queue / Large Load Registry scraper: the source updates on a disclosure cadence, there is
  nothing to poll continuously
- The monthly zone x month correlation join
- Backfill, when run

Steady state should sit near 5–6GB, leaving genuine headroom rather than running at 65%
committed on a box with no vertical scaling path.

### Local fallback (if the Oracle VM is unavailable)

A1 capacity shortages and instance reclamation are both real (Section 3), so the build must
never depend on the VM existing:

- **Phases 1–4 need no cloud at all.** Docker Compose covers day-to-day development, and a
  local **`kind`** cluster validates the actual Kubernetes manifests, meaning Phase 5
  becomes "apply known-good manifests to a different cluster" rather than a first attempt.
  Chosen over k3d/minikube specifically so local validation uses the same tool as CI
  (Section 7, Phase 5) instead of a third variant that could behave differently; k3d would
  arguably mirror the Oracle VM's real k3s more closely, but matching CI avoids
  works-locally-fails-in-CI drift, and CI already proved this choice works.
- **For demoing without a public IP**, a Cloudflare Tunnel (or Tailscale Funnel) exposes a
  local Grafana over HTTPS on a real hostname. Good for a live interview demo; not a
  substitute for 24/7 hosting, since it's only up while the machine is.
- **For genuine 24/7 if Oracle never comes through**, the honest answer is a ~$5/month VPS,
  not another free tier. The stack is portable by design: k3s manifests plus two API keys.

### Public dashboard: provisional panel sketch

Rough shape, to be refined in Phase 4 once there's real data to look at; recorded here so
the dashboard is designed rather than assembled from whatever queries happen to exist:

1. **Header stat row**: current PJM demand, 24h peak, data freshness ("last EIA reading:
   N hours ago"), anomalies flagged in the last 7 days.
2. **Demand vs forecast, last 7 days**: actual load line with the forecast band behind it;
   flagged intervals marked. This is the project's single money panel.
3. **Forecast residuals**: the series the detector actually scores, with the alert
   threshold drawn in, so a visitor can see *why* something was flagged.
4. **Anomaly log table**: timestamp, magnitude, residual, duration; most recent first.
5. **Generation mix over time**: stacked area, context rather than detection.
6. **Model methodology footer**: plain-language note on the time-based split, the baselines
   it was measured against, and an explicit statement that anomaly labels don't exist.

Panels 1–4 are the story; 5–6 are credibility. Nothing here touches a PJM-sourced table.

### Public access: domain + TLS

A bare Oracle IP doesn't give you clean HTTPS, and a raw `https://1.2.3.4` link looks
unfinished. Plan:

1. Reserve a Oracle Cloud **Reserved Public IP** (see risks above) and attach it to the VM.
2. Register a free subdomain pointed at that IP: a free dynamic-DNS provider (e.g. DuckDNS)
   is the simplest option and takes minutes.
3. k3s ships with Traefik as its default ingress controller; use it (or add cert-manager)
   to terminate TLS automatically via Let's Encrypt against that subdomain.
4. Only route the subdomain to the externally shared dashboard's URL (the specific
   public-tier dashboard); don't expose the rest of the Grafana instance, Kafka, or Postgres
   through the ingress at all.

## 6. Data & modeling methodology

Decided up front because these choices shape what gets logged from day one, and because
Section 2 commits to an honest write-up rather than an impressive-sounding one.

### Historical backfill

The live pollers alone can't train anything: a model needs years of history before the
first real-time message arrives. Backfill is therefore a first-class part of Phase 1, not
an afterthought.

- Loaders live in `/ingestion/backfill/` and write **the same Postgres tables, through the
  same normalization code, as the live pollers.** Train-time and serve-time data must be
  identical in shape, or the evaluation is measuring the wrong thing.
- Idempotent **and revision-aware**: `ON CONFLICT (source, zone, interval_start) DO UPDATE`
  when the value actually changed, with a `retrieved_at` column recording when each version
  was fetched. `DO NOTHING` would be simpler and wrong: EIA restates published figures, and
  first-write-wins would permanently freeze whichever value happened to arrive first.
  Runnable both as a CLI (`python -m ingestion.backfill --source eia --start 2019-01-01`)
  and as a K8s Job.
- **The live poller re-pulls a rolling 72-hour window every cycle**, not just the newest
  hour. This absorbs both the publication lag and the revisions in one mechanism, and means
  the live path and the backfill path converge on identical values rather than drifting
  apart. Train/serve skew is prevented here, at ingest, not patched later in the model.
- **Cadences:** EIA hourly (the data is hourly; polling faster just re-reads the same rows),
  PJM every 5 minutes to match its refresh, queue/registry on a daily check that no-ops
  unless the source document changed.
- **EIA:** pull PJM BA hourly demand, net generation, and interchange from **2019-01-01**
  onward (sub-regional/by-source data starts July 2018, so 2019 is a clean full-year
  boundary). That is roughly 60k hourly rows, trivial for Postgres. Paginate around the
  API's 5,000-row response cap.
- **PJM: confirmed live (2026-10-13) that deep history is genuinely expensive, not just
  slow.** The original "2+ years" target assumed server-side zone filtering stayed available
  throughout; it doesn't. `rt_fivemin_hrl_lmps` archives data after `archiveCutoffDays`
  (186 in its live metadata, about 6 months, not the "two years" its prose description
  implies). Past that boundary, PJM rejects both a `pnode_id` filter and a custom sort/order
  on the same request, so there is no server-side way to narrow to the 5 PA zones: every
  request returns all ~14,700 PJM nodes for whatever interval it covers, and the 5 zone rows
  get picked out client-side. Even at the coarsest (hourly) grain that's roughly 3 pages per
  hour just to enumerate everything once, so a year of archived hourly history is on the
  order of 26,000 requests, about 3.5 days at the 11-second pacing this project's PJM client
  enforces to respect the 6 req/min non-member limit (confirmed by tripping a 429 during
  testing).
  - **Default backfill clamps to the non-archived window** (~170 days with a safety margin),
    where the fast, zone-filtered, 5-minute-granularity path applies, proven live: 30 days
    x 5 zones backfilled in well under 15 minutes, exactly 8,640 rows per zone per 30-day
    chunk as expected.
  - **Deeper history is possible, not automatic.** `run_archived_backfill` (ingestion/
    backfill/pjm_backfill.py) implements the slow, all-nodes, hourly path correctly and is
    tested, but is multi-day by design and meant to be launched deliberately as a long-lived
    background job, never bundled into routine setup.
  - **Net effect on the model:** PJM's effective training window is shorter than EIA's
    unless someone explicitly runs the archived backfill. That's an honest limitation to
    state in the methodology write-up (Section 6), not a bug to hide.

### Train/validation/test split

- Strictly time-ordered, never shuffled. Scalers, thresholds, and contamination parameters
  are fit on **train only**: leakage sneaks in through the scaler far more often than
  through the model itself.
- Public (EIA) tier, concretely: **train 2019-01-01 → 2025-06-30, validation 2025-07-01 →
  2025-12-31, test 2026-01-01 → freeze date.** The test window is touched once, at the end.
- These dates live as frozen constants in `/model/splits.py`, not as notebook variables
  that quietly drift between runs.

### Feature design: what actually gets scored

The most consequential modeling decision in the project, and the easiest one to get
silently wrong.

- **Score forecast residuals, not raw levels.** An isolation forest fed raw demand will
  flag every July afternoon and every January cold snap, correctly, in that those hours
  are statistically extreme, and uselessly, in that everyone already knows summer is hot.
  Scoring `actual - forecast` instead makes an anomaly mean *"the grid did something the
  model did not expect"*, which is the actual story and the thing a data-center-driven
  deviation would show up in.
- This also makes the forecaster load-bearing rather than decorative: it earns its place by
  defining the baseline the detector measures against, which is a cleaner justification
  than "the architecture called for an LSTM".
- **Features:** residual plus calendar context (hour-of-day, day-of-week, holiday flag) and
  short-window rate of change. Deliberately not weather, at least at first. Weather
  explains most load variance, so including it makes the model better at forecasting and
  worse at *surfacing* the unexplained behaviour this project is looking for. Revisit
  during the weather-normalization work in the correlation layer.
- **Missing data has an explicit policy, decided before training.** EIA-930 has gaps and
  nulls; untreated, a gap looks exactly like the flatline pattern the synthetic-injection
  harness tests for, so the evaluation would end up scoring data-quality artifacts and
  calling them anomalies. Rule: forward-fill gaps of 1–2 hours, mark longer gaps as
  `quality = 'missing'` and exclude them from both training and scoring, and surface
  gap counts on the dashboard rather than hiding them.
- **Implausible values are a real, separate failure mode from gaps, found running this
  against live data (2026-10-13).** 3 rows out of 68,226 had demand values up to
  2,147,480,000 MW, suspiciously close to 2^31-1, a classic 32-bit overflow/sentinel
  value, strongly suggesting a data-quality incident on EIA's own side rather than anything
  in this project's ingestion path (the same incident hit net generation too, same 3 rows,
  same exact value). These are present, not missing, so the gap policy above never touched
  them; a naive baseline trained on raw values had its MAPE corrupted from a plausible ~11%
  to ~88% by three rows. Fix: `model/data.py`'s `PLAUSIBLE_BOUNDS_MW` masks anything outside
  a sane range to NaN before the missing-data policy runs, per reading type, so an
  implausible reading flows through the exact same fill/exclude logic as any other gap.
  **Bounds are reading-type-specific on purpose, confirmed necessary live:** demand and net
  generation share [1,000, 250,000] MW (PJM's actual all-time peak is roughly 165,000 MW),
  but total interchange is legitimately signed (observed live range: -4,456 to 15,772 MW,
  ordinary imports/exports) and gets a wide symmetric band instead, [-100,000, 100,000],
  reusing the demand floor there would wrongly mask most interchange hours, since negative
  is the normal case, not an error.
  - **This masking approach does NOT transfer to PJM LMP data, and must not be copied
    there.** Checked live: PJM zone prices range from about -$611/MWh to +$4,251/MWh across
    the five PA zones, with no sentinel-style garbage observed. Both extremes are genuine
    electricity-market phenomena, not errors: negative prices happen during oversupply
    (high renewable output, low demand), spikes happen during genuine scarcity. Those
    extremes are exactly the signal the anomaly detector exists to find; clipping them the
    way EIA demand is clipped here would delete the thing the private tier is built to
    surface. Any PJM-side data-quality check needs its own, separate reasoning, not a
    copy-paste of this EIA-specific one.

### Evaluating an unsupervised detector (the honest version)

There are no ground-truth anomaly labels for this data. That constraint is stated plainly
in the README rather than papered over with a precision/recall number that doesn't exist.

- **The forecast model carries the quantitative claim.** MAE / MAPE / RMSE on the held-out
  test window, reported against two baselines: seasonal-naive (same hour, previous week)
  and a day-of-week × hour-of-day profile regression. **Both baseline numbers get published
  alongside the model's.** If the LSTM doesn't beat them, the README says so and the
  baseline stays in production, that is a better engineering story than a model that wins
  on narrative only.
  - **Real numbers, validation window (2026-10-13 run, public/EIA tier):**
    seasonal-naive MAE=8,180 MAPE=8.15% RMSE=10,962; day-of-week × hour-of-day profile
    MAE=11,807 MAPE=11.13% RMSE=15,713 (n=4,392 hours each). Seasonal-naive beats the
    profile baseline, a genuinely interesting result worth keeping in the methodology
    write-up rather than just a number: the profile averages over the *entire* ~6.5-year
    training window, which smooths out the longer-term demand growth this project's whole
    thesis is about, while seasonal-naive only looks back one week and tracks a moving
    baseline more closely. The isolation forest's residuals should be scored against
    seasonal-naive specifically, since it is the stronger of the two.
  - **Private (PJM) tier, same methodology applied with its own reasoning, not copy-pasted
    (2026-10-13 run, PJM's own split dates, Section 6/splits.py):** per zone, e.g. PECO
    seasonal-naive MAE=25.4 RMSE=103.9, profile MAE=30.5 RMSE=99.9 (n=10,368 five-minute
    intervals). Two real, tier-specific findings, not just different numbers: **MAPE is
    reported as "n/a" rather than a number** for every zone, because real LMP prices cross
    zero routinely (confirmed: at least one exact $0.00/MWh reading in the validation
    window alone) and MAPE's denominator is `|actual|` -- division by zero, not a rare edge
    case for this tier. `model/evaluate.py`'s `ForecastMetrics` now reports MAPE as `None`
    with a plain explanation rather than a meaningless `inf%` whenever this happens, instead
    of silently printing a number that looks precise and isn't. Second: **seasonal-naive
    wins on MAE in 4 of 5 zones, but the profile baseline wins on RMSE in every zone** --
    the opposite of a clean sweep in either direction, suggesting naive makes smaller
    typical errors while profile avoids large outlier misses more consistently. Left as an
    honest, mixed result rather than picking one winner to declare.
- **The anomaly detector gets a two-part evaluation:**
  1. *Synthetic injection (quantitative).* Inject labeled perturbations into held-out data
     at known timestamps: step changes, spikes, flatlines (stuck-sensor), and abnormal
     ramps, then report recall at a fixed alert budget (at most 1% of intervals flagged).
     This measures sensitivity against known-bad signals without pretending the real data
     is labeled.
  2. *Event correspondence (qualitative, labeled as such).* Do flagged intervals line up
     with known real events: heat waves, winter storms, PJM cold-weather alerts and
     emergency procedures? Presented as a sanity check, never as a metric.
- Operating threshold is chosen on **validation**, frozen, then reported on test.
- **Real synthetic-injection results, two rounds, both run live against the real backfilled
  data (2026-10-13), 1% alert budget throughout.** First round, with the original 5-feature
  set (residual, hour, dayofweek, is_holiday, rate_of_change): a large negative spike
  (residual -31,852) caught at 100%, an equally large positive spike (+44,851) at 0%, step
  change at 8.3%, flatline and abnormal ramp both at 0%. The asymmetry and the misses
  were explainable, not a bug: the clean validation residual distribution already has a std
  of ~10,918 and real values from -44,721 to +27,081, so a single-hour point anomaly only
  stands out if it's extreme relative to that already-wide natural tail; flatline and
  abnormal-ramp are genuinely multi-hour **pattern** anomalies, and nothing in that feature
  set aggregated across hours to see a pattern.
  - **Fix, also real and tested live:** two rolling-window columns added to
    `model/features.py`: `rolling_std` (trailing 4h) and `rolling_rate_of_change_mean`
    (trailing 4h), specifically so a stuck sensor or a sustained drift produces a visibly
    unusual row instead of several individually-unremarkable ones.
  - **Second round, 7-feature set, same magnitudes:** spike recall went to 100% both
    directions, step change improved from 8.3% to 41.7%. Flatline and abnormal ramp were
    *still* 0% at the original magnitudes, which prompted one more check before accepting
    that result: is this still a magnitude-calibration problem, or has it become genuinely
    structural? Tested both anomaly types at deliberately larger magnitude/duration to find
    out:
    - **Abnormal ramp: magnitude calibration, not a detector problem.** At 100,000 total
      magnitude over 10h (vs. the original 30,000), recall jumped to 80%. `rolling_rate_of_
      change_mean` genuinely works; the original test magnitude simply wasn't extreme
      relative to real demand's natural ramping (training data's own max for that feature
      is 34,614, bigger than the original injection's peak).
    - **Flatline: genuinely structural, confirmed by ruling out magnitude.** Tripling the
      duration to 24 hours (a full day stuck) still scored 0% recall, with the maximum
      score among injected positions still negative (looking *more* normal than average).
      `rolling_std` does correctly collapse to exactly 0, below even the training window's
      observed minimum, but that one informative signal gets diluted across 6 other
      mostly-irrelevant features in the isolation forest's random per-split feature choice,
      and more duration doesn't fix dilution the way more magnitude fixes a weak signal.
  - **Left as a named, understood limitation rather than chased further.** A targeted fix
    exists (e.g. a simple rule-based check: rolling_std under some floor for N consecutive
    hours, running alongside the isolation forest rather than as one of its diluted input
    features) but is a different kind of detector, a real design decision, not a one-line
    change, and is deliberately left for a future iteration. The pattern across this whole
    evaluation exercise: investigate until the *why* is understood and defensible, then stop
    and document precisely, rather than keep tuning until one aggregate number looks better.
  - **Cross-tier confirmation (2026-10-13): the exact same pattern reproduces on PJM LMP
    data** (PECO zone, 5-minute grain, completely different data type and scale from EIA
    demand), not just repeated on the same dataset. Spikes: 100% recall both directions.
    Step change and abnormal ramp: both 0% at an initial conservative magnitude, then 45.8%
    and 83.3% once properly calibrated against PECO's own real residual tail (-628 to
    +2,661 $/MWh, confirmed before picking magnitudes rather than guessed) -- magnitude
    calibration again, not a detector problem, same as the EIA ramp finding. **Flatline:
    0% recall even at 8 hours** (3x the EIA test's duration), confirming this is a property
    of the isolation-forest-over-mixed-features approach itself, not an artifact of EIA's
    specific data or feature choices. Strengthens the case that the real fix (a separate
    rule-based check, not another diluted input feature) is worth building once, serving
    both tiers, rather than two independent patches.
  - **The rule-based fix, built and run for real (2026-10-13), closes most of the gap.**
    `model/flatline_detector.py`: a plain threshold check (rolling_std at or below a
    train-calibrated floor, for at least as many consecutive periods as the rolling window
    itself) running ALONGSIDE the isolation forest rather than as one more diluted input,
    which is exactly why it works where the forest alone doesn't -- a single-feature rule
    has no dilution to lose signal to. EIA: flatline recall 0% -> 75% combined (forest OR
    rule), everything else unchanged, rule's false-positive rate on real clean validation
    data 0.18%. PJM, all 5 zones: flatline recall 0% -> ~90% combined (89.6-90.6% across
    zones), 0.00% false-positive rate in every zone -- the fix is at least as effective on
    PJM as on EIA, a second cross-tier confirmation in the fix's favor, not just the gap's.
  - **One more honest finding from running all 5 PJM zones, not just PECO:** DUQ recalled
    noticeably worse than the other four on the fixed-magnitude injections (negative spike
    0% vs. 100% elsewhere, step change 4.2% vs. ~46%) -- not a bug, confirmed by checking
    DUQ's own residual distribution: std of 234.0 against PECO's 103.8, real tail reaching
    -2,119 to +4,164 against PECO's -628 to +2,661. The same fixed injection magnitudes,
    deliberately reused across all five zones rather than re-tuned per zone, are simply
    less extreme relative to DUQ's naturally noisier baseline. The flatline rule (which
    calibrates its own floor per zone on that zone's train data) was unaffected by this and
    performed consistently across all five -- the gap is specific to the fixed-magnitude
    synthetic test, not the detector.
  - **The out-of-sample flag rate (2026-10-15).** The private page showed about 3% of
    intervals flagged against a 1% budget, and nothing in the evaluation above reported the
    realized flag rate on data the threshold was not calibrated on, so
    `scripts/evaluate_flag_rate_pjm.py` now does, per zone, with event counts. Results across
    the five zones: validation 1.00% (by construction), the frozen test window (2026-09-20
    to 10-13) **0.47%**, and the post-freeze days 10-13 to 10-15 **5.9%**. The detector is
    calibrated and slightly conservative on the test window. The post-freeze figure is
    one volatile stretch, not drift: it is about 12 distinct events over 3 days across all
    five zones, 72% of the flagged intervals fall on prices that are themselves beyond
    +/-$300/MWh, and those prices are verified settlement-quality values, not provisional
    ones (about 2% of all verified intervals since September exceed $300 in absolute value,
    so spikes are ordinary here and cluster). A flag rate over a few days therefore says
    mostly how volatile those days were; the budget is a statement about a calm calibration
    window, and event counts are the number to quote.
    A second effect is real but small: the one-week seasonal-naive baseline replays a spike a
    week later, so a calm interval one week after a spike is flagged as a surprise (an
    "echo", 10 of 247 post-freeze flags). A baseline using the median of the last three
    weeks removes most of them (10 to 2) but moves the test rate only from 0.47% to 0.40%
    and the post-freeze rate from 5.9% to 5.6%, so it was not adopted; the script prints
    both so the decision stays checkable. One caveat on process: the post-freeze window was
    looked at while diagnosing this, so it is not a clean holdout for the comparison.

### Retraining, drift, and cold start

There's a real tension here, and naming it is better than silently picking a side:

- **Retrain the detector too often and it erases the project's own thesis.** If the training
  window keeps sliding forward, the model gradually learns that the new, higher,
  data-center-inflated baseline is perfectly normal, normalizing precisely the trend the
  project exists to highlight. Never retrain, and it drifts until everything looks anomalous.
- **Resolution: freeze the detector, schedule the forecaster.** The anomaly detector keeps a
  fixed training window so "anomalous" stays anchored to a stable historical definition. The
  forecaster retrains monthly so predictions track reality. Each retrain is versioned and its
  test-window metrics recorded, so regressions are visible rather than inferred.
- That tension is worth a paragraph in the README on its own: it's a more interesting
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
- `interconnection_queue` is stored as **slowly-changing snapshots**:
  `(snapshot_date, project_id, zone, mw, status)`, never overwritten in place. Without
  point-in-time reconstruction you can't say what the queue looked like back when a given
  month's stress actually occurred.
- **Claim discipline.** This is observational, with 5 zones and a few dozen months; queued
  MW is not energized load; weather, fuel prices, and transmission outages are obvious
  confounders. It ships as a described correlation with the confounders named in the
  README, never as a causal claim. Weather-normalizing load against NOAA HDD/CDD before
  making any load-growth statement is the stretch version of doing this properly.
- **The public tier has no correlation panels at all.** EIA-930 is BA-level with no PA zone
  breakdown, so the correlation story is structurally private-tier-only. That is a data
  limitation, not only a licensing one.

## 7. Engineering conventions

Defaults chosen to fit 2 OCPUs / 12GB of ARM; change them if there's a reason, but each
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
  - *Public (EIA) tier*: artifact baked into the image, published to public GHCR, attached
    to git releases. Federal public-domain input, nothing to protect.
  - *Private (PJM) tier*: artifact **never committed and never baked into a public image**.
    It lives on a PVC on the VM (and locally for development), mounted at runtime; if baking
    it in is ever more convenient, that image goes to a *private* GHCR package. The
    distinction is deliberate: publishing a model trained on PJM data publishes PJM-derived
    material just as surely as committing a CSV would.
- **PyTorch, not TensorFlow**: the arm64 wheel story is dramatically cleaner, plus
  scikit-learn for the isolation forest. The LSTM only ships if it beats the baselines.
- **Images are `linux/arm64`** (Ampere A1), built with `docker buildx`, Python slim base,
  no conda. Published to **GHCR**: public for the EIA tier, private for any image carrying
  a PJM-trained artifact.
- **CI/CD is pull-based** (stretch goal 1). GitHub Actions lints, tests, and pushes to
  GHCR; the cluster pulls. The k3s API server is never exposed to the internet; admin
  access is SSH-only, so there is no inbound cluster credential for CI to hold or leak.
- **Secrets are never committed.** Local dev reads a gitignored `.env` alongside a
  committed `.env.example`; the cluster uses Secrets created out-of-band with `kubectl`,
  referenced by name from the manifests. If PKI client certs turn out to be required,
  they're mounted as files from a Secret, not stuffed into env vars. SOPS/sealed-secrets
  only if the manifests ever need to be fully self-contained.
- **Postgres is the system of record; Kafka is transport.** Kafka retention stays short
  (24h or a small size cap) so it can't eat the volume. No backup requirement: every row
  is re-derivable by re-running backfill against both APIs, and public-tier model artifacts
  live in git releases (private-tier artifacts are re-trainable locally from Data Miner, per
  the artifact rule above).
- **Resource limits on everything.** Single Kafka broker in KRaft mode with a capped heap
  (512MB–1GB), Prometheus at 15d retention and a 30s scrape interval, explicit small
  requests/limits on Grafana and Postgres. Target: roughly 2GB headroom free at steady
  state.
- **Config is env-var driven via pydantic-settings**, so Compose and k8s run the same code
  path with different values.
- **Tests are pytest, with API clients exercised against recorded fixtures**: CI makes no
  live API calls (the 6 req/min PJM limit alone makes that a bad idea). CI runs ruff +
  pytest + an arm64 image build on every push.
- **No PyTorch in any serving container.** Forecasts are generated by a scheduled CronJob
  and written to Postgres; the inference services carry scikit-learn only. This is both a
  memory decision (~150MB vs ~400MB per replica, twice over) and a simpler one: Grafana
  reads predictions from Postgres regardless, so a live torch process was never on the read
  path to begin with.
- **Normalization lives in `/common`, not in the Kafka consumer.** There are two write paths
  into the same tables: live (poller → Kafka → consumer → Postgres) and bulk (backfill →
  Postgres), and the "train and serve see identical data" guarantee in Section 6 only holds
  if both import the same transformation code. Putting it in the consumer quietly breaks
  that the first time backfill runs.
- **Migrations are plain numbered SQL files** applied by an init job, not Alembic. The
  schema is a handful of tables; a migration framework is a dependency and a failure mode
  this project doesn't need to buy.
- **Dashboards are code.** Grafana dashboards are provisioned from JSON committed to the
  repo, never clicked together in the UI. Losing the VM should cost an afternoon of
  redeployment, not the project's entire visible output. (PJM dashboard JSON contains panel
  definitions and queries, not data, but check it for embedded sample values before
  committing, per the Section 2 publication policy.)
- **The pipeline must alert on its own death.** A silently dead poller is the single most
  likely real failure, and a dashboard of stale data is visually indistinguishable from a
  quiet grid. Minimum metrics from every service: time since last successful ingest (per
  source), API error rate, Kafka consumer lag, inference latency, and anomalies flagged per
  hour. **One Prometheus alert on ingest staleness is worth more than all the others
  combined**: if only one alert ever gets written, write that one.
- **Logs are structured JSON to stdout**, read via `kubectl logs`. No Loki, no log
  aggregation stack: it would cost ~500MB to solve a problem this project doesn't have yet.

## 8. Proposed repo structure

```
/common              shared config (pydantic-settings), Kafka + Postgres clients,
                     logging, Prometheus metric helpers, used by every service
/ingestion
  eia_poller/        public-tier poller (EIA-930, hourly)
  pjm_poller/        private-tier poller (PJM Data Miner, 5-min)
  queue_scraper/     interconnection/Large Load Registry batch job
  backfill/          idempotent historical loaders, same tables, same normalization
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
/notebooks           exploration only, nothing here is on the serving path
/.github/workflows/ci.yml   ruff + pytest + arm64 image build on every push
README.md             documents the public/private data split explicitly for anyone
                      reading the repo (including why), plus the model methodology
                      write-up (what was validated, what wasn't)
.env.example          every env var the stack reads; the real .env is gitignored
```

## 9. Build phases

1. **Ingestion + storage**: EIA poller (public tier) first since it's unblocked and
   zero-risk, plus the EIA **backfill** to 2019 in the same pass (the model has nothing to
   train on without it); PJM poller and its 2-year backfill once non-member access is
   provisioned. Queue scraper/Large Load Registry confirmed deferred (Section 3): no access
   mechanism exists yet, revisit after PJM's compliance filing. Postgres schema for all
   tiers in scope, UTC `timestamptz` throughout. Confirm the PKI auth question here first;
   don't proceed past this phase on unverified assumptions.
2. **Model**: baselines first (seasonal-naive, day×hour profile), then isolation forest
   and optionally an LSTM forecast per tier, on the frozen time-based split from Section 6.
   Build the synthetic-injection harness here too: it is the only quantitative handle on
   the detector. Write up the methodology honestly: what was validated, what wasn't, and
   the baseline numbers next to the model's.
3. **Pipeline wiring**: Kafka producers/consumers for both tiers, FastAPI inference
   service(s), Docker Compose local stack end-to-end.

   Built and verified (2026-10-13), no Docker/admin rights available on the dev machine, so
   Kafka (KRaft mode, single broker), Postgres, and the two inference services were run
   against the real stack through portable binaries (no containers) instead:
   - Manual Kafka offset commits only after a successful Postgres write, confirmed against
     a real broker with both a dropped-write and a successful-write test case.
     `KafkaError.retriable()` looked like the right signal for "nothing to read yet" and
     turned out not to be: `UNKNOWN_TOPIC_OR_PART` has `retriable() == False` even though
     polling again a moment later works with no special handling. Replaced with a curated
     set of non-fatal error codes, confirmed against the real broker, not assumed.
   - Model artifacts persisted via `joblib` (`model/artifact.py`), trained off-cluster
     (`scripts/train_detector_eia.py`, `scripts/train_detector_pjm.py`), loaded by each
     inference service at startup rather than re-fit per container start. Confirmed
     identical scores before and after save/load for both tiers.
   - The race between the inference service's own scoring and the separate raw-write
     consumer (both read the same Kafka topic independently, no ordering guarantee between
     them) is avoided by design: the point being scored always comes from the Kafka message
     itself; Postgres is only queried for history strictly before it.
   - Real-time round trip confirmed for the EIA service: a fresh row produced to Kafka
     reached a written anomaly row in Postgres in under 5 seconds. A force-killed service
     instance (`Stop-Process -Force`, the equivalent of a container being killed without a
     grace period) left a stale session on its consumer group, delaying the next instance's
     rebalance well past the broker-reported lag reaching zero, not a code bug but a real
     reason production should terminate these processes with a grace period, not a hard
     kill.
   - The PJM service's live round trip could not be demonstrated the same way during this
     pass: its seasonal-naive lag needs roughly a week of dense trailing history, and
     `pjm_lmp_readings` had a real multi-hour gap right before the current time because the
     PJM raw-ingestion consumer hadn't been running continuously. The unverified live feed
     only ever returns the most recent interval, so that gap cannot be backfilled after the
     fact; the verified feed that could backfill it reconciles the next day. The service
     correctly declined to score rather than scoring on a thin window, confirmed as
     intended behavior via a mocked-history unit test, the same way the EIA service's logic
     was unit-tested before its live demo.
   - `docker-compose.yml` and the two inference-service Dockerfiles (matching Section 7's
     per-tier artifact policy: the EIA image bakes its artifact in, the PJM image mounts it
     at runtime) could not be run locally, this dev machine has no Docker install, so
     verification moved to CI instead: a dedicated GitHub Actions job builds all three
     images for real and brings up Postgres, Kafka, and both inference services together
     (never the pollers, which would make live API calls), using throwaway detectors fit on
     synthetic data since CI has no real EIA/PJM history to train on. Confirmed green
     (2026-10-14): both inference services report their model loaded and their Kafka
     consumer attached on a real Docker install, which is what this verification needed
     to prove.
4. **Observability**: Prometheus + two Grafana dashboards: the public one (EIA-only data,
   shared via Grafana's Externally Shared Dashboards feature) and the private one (PJM zone
   data; the data-center correlation panel is deferred, see Section 3, so this is PJM zone
   data alone for now). Double-check the public dashboard genuinely has zero PJM-sourced
   panels before enabling external sharing.

   Built (2026-10-14): `common/metrics.py` gained the inference-side counterparts to the
   existing ingestion metrics (scoring outcome, anomalies flagged by detector type, scoring
   latency, last-successful-score staleness gauge), wired into both inference services and
   confirmed emitting real values against a live local run, not just unit-test mocks.
   `infra/prometheus/prometheus.yml` and `infra/grafana/provisioning/` (datasources +
   dashboard provisioning) were added, plus both dashboards as provisioned JSON files
   (`infra/grafana/dashboards/`), matching the panel sketch above. One real correction made
   while building it: EIA-930 only reports a single net-generation aggregate, not a
   fuel-type breakdown, so the sketch's "generation mix" panel became "net generation and
   total interchange" instead, an honest label for what the data actually supports.
   Forecast values are derived in-query as `actual - residual` rather than stored
   separately, since the `residual` column already carries that information.

   Confirmed green (2026-10-14): CI's extended compose-smoke-test passes, Prometheus
   actually scrapes both inference services and Grafana provisions both dashboards and
   reaches the Postgres datasource, on a real Docker install. Took three real bugs to get
   there, each a genuine finding, not CI flakiness: a Grafana bind-mount nested inside an
   already-read-only mount (fixed by moving the dashboard JSON files so one mount covers
   everything, no nesting); checking Prometheus/Grafana target and provisioning health
   exactly once right after the app's own HTTP server responds, which races their own
   async scrape/provisioning cycles (fixed by retrying each check independently); and
   Grafana's datasource health endpoint being UID-based (`/api/datasources/uid/:uid/health`),
   not the ID-based path first assumed.
5. **Deploy**: write the Kubernetes manifests and validate them on a **local `kind`
   cluster first**, so the Oracle deploy is "apply known-good manifests" rather than a first
   attempt (and so an A1 capacity shortage delays nothing). Then Oracle Cloud VM + k3s, live
   24/7. Reserve the Oracle Public IP, point a free subdomain at it, wire up Traefik/cert-manager for Let's Encrypt
   TLS (see "Public access: domain + TLS" above) before calling the public link done.

   Built and confirmed green in CI (2026-10-14): plain manifests for every service
   (`infra/k8s/`, no Helm/Kustomize), a CI job that builds and pushes all three images to
   GHCR, spins up a disposable `kind` cluster, applies everything except the Ingress
   (needs cert-manager installed first), populates the PJM artifacts PVC through a
   documented loader-pod procedure, and confirms both inference services healthy through
   real K8s Services. Passed on the first run, no debugging round needed, unlike Phase 3/4's
   Docker Compose verification. What this does not yet prove: the real Oracle VM itself
   (this ran against a throwaway `kind` cluster on a GitHub Actions runner, not the actual
   1 OCPU/6GB target) and the Ingress/cert-manager/TLS path, which needs a real registered
   subdomain and a cluster with cert-manager installed, neither of which exist yet. See
   `infra/k8s/README.md` for the current state in full.

   **The actual Oracle VM is paused, not abandoned (2026-10-14).** Always Free Ampere A1
   capacity is genuinely out across all three Ashburn availability domains right now, a
   real, widely-reported Oracle limitation, not a configuration mistake -- confirmed by
   hitting "out of capacity" on AD-1, AD-2, and AD-3 in turn. Rather than block on Oracle's
   capacity recovering, the project proceeds locally for now: CI's `kind`-based verification
   already proves the manifests work, which is the thing that actually mattered before any
   real deploy. The Local fallback section above (Section 5's "if the Oracle VM is
   unavailable") already anticipated exactly this. Revisit the real VM (or a ~$5/month VPS
   fallback, same section) once there's a reason to prioritize 24/7 public hosting over
   continuing other work.
6. **Stretch** (in priority order): CI/CD auto-deploy, Slack/email alerting, Terraform IaC.
7. **Custom frontend** (decided 2026-10-14, design finalized 2026-10-15, replaces both
   Grafana dashboards): Next.js (App Router, TypeScript) in `frontend/`, deployed to Vercel,
   reading Postgres directly via parameterized SQL in TypeScript query functions (Route
   Handlers as serverless functions) -- the same "reads Postgres directly" pattern Grafana
   already used, not a new API layer. The website reads Neon (serverless Postgres, free
   tier). The pipeline does NOT write to Neon: it keeps writing to the local Postgres, and an
   hourly sync copies new rows across (see "Neon sync" below). The historical data was
   loaded into Neon once via `pg_dump`/restore, not re-backfilled.
   Charts are the project's own hand-rolled SVG renderer (already used in the case-study
   page), ported into React components -- no new charting dependency.

   **Public/private split, driven by a licensing constraint, not just a design choice:**
   PJM's Data Miner 2 API terms prohibit non-member redistribution of data "contained in or
   derived from" it (confirmed live via PJM's own API portal terms, 2026-10-15); this
   project's key is non-member. So only EIA-930 data (federal, unrestricted) is public
   (`/`, `/demand`); PJM zone data (LMP, load, and the PPL promises-vs-measured comparison
   that depends on it) lives behind a single shared-passcode gate (`/private/zones`,
   `/private/accountability`), mirroring the split `private_pjm.json`'s own methodology
   panel already documented. `docs/index.html` (the static case-study mock) currently
   violates this by showing PJM-sourced figures publicly; left as-is for now by deliberate
   choice, not fixed as part of this build. Resolving a real PJM Redistribution License, if
   ever pursued, would be a separate follow-up that could later make the accountability
   content public. Uses the `pbakaus/impeccable` design plugin for the UI pass.

   **PA map and citations (2026-10-15).** `/map` is a public interactive map of PA counties,
   utility service territories, and publicly reported data center projects. It is prerendered
   static content and reads no database, so it cannot carry PJM data. `/private/map` is the
   same component with a zone overlay (LMP and anomaly counts) supplied only through that
   private route. Geometry is public: U.S. Census-derived county polygons and HIFLD retail
   service territories (served by PASDA). The project list is hand-curated from public
   reporting, one entry per project with the sources actually read, and is not a registry:
   no authoritative public dataset exists. It lives in `scripts/map/data_centers.json`, and
   `python scripts/map/build_map_data.py` regenerates `frontend/src/data/paGeo.ts` and
   `dataCenters.ts` from it (county and utility are computed by point-in-polygon). Statuses go
   stale quickly, so each project carries an as-of date and entries that were denied or
   abandoned stay on the map, marked as ended. Quoted sources on the site go through one
   registry (`frontend/src/lib/sources.ts`) rendered as numbered citations and a generated
   reference list.

   **Map status, nearby people and plants (2026-10-15).** Each project has a status category
   (announced, under local review, approved for a first phase, under construction, rejected
   locally, abandoned), drawn as a distinct marker shape as well as a color, and filterable
   with chips that show counts. The `ended` flag is now derived from the abandoned category.
   For projects placed at a specific site (`precision: "site"`), `scripts/map/exposure.py`
   counts people and homes within 0.5, 1, 2 and 5 miles from 2020 Census PL 94-171 block
   files (keyless bulk download, cached under `scripts/map/.cache/`, with each state's block
   sum checked against its state total), loads neighboring states only when a 5-mile circle
   crosses the line, and lists schools, hospitals, nursing homes and child care within a mile
   from HIFLD layers on PASDA. Blocks are assigned by internal point, so counts near a ring
   edge are approximate, and Census disclosure avoidance adds noise to small blocks.
   Municipality-level projects show "not measured" rather than a guessed number. The panel
   states that proximity is not impact, and there is deliberately no risk score. Two projects
   (York 2, Aligned Shippingport) carry `locateAtPlant` and are pinned to the named plant
   from the HIFLD plant layer. The optional plant layer shows operating plants of 100 MW or
   more, and each measured project lists its nearest one. The local response notes are
   written only from sources actually read, each with a link and date. Search, status filters
   and the selected project are kept in the URL (`project`, `status`, `q`), read after
   hydration so the prerendered page is identical for everyone, and a sortable table below
   the map shares the same filters. With rings on, the map zooms to a window around the
   project so the 1 and 5 mile rings are legible. Not covered: planned housing, noise, water
   or emissions modeling, and projects not yet found in reporting.

   **Growing the project list (2026-10-15).** The list went from 13 to 44 projects by using
   trackdatacenters.com's Pennsylvania page only as a lead list of names (its pages cite no
   external sources, so none of its statuses or figures are used). Each project was then
   searched, and an entry was added only when a news article, company release or similar
   source was actually read and supports the status. Each status carries its own as-of date
   and the sources read. About 70 of the site's 163 entries are existing colocation or
   telecom facilities, which are out of scope for a map of proposed projects. Entries it
   lists that could not be verified from a readable source are left off rather than guessed.
   Placement uses `scripts/map/locate.py`: a street address through the Census geocoder
   gives precision "site", otherwise the Census 2020 internal point of the township, borough
   or city gives precision "municipality" (shown as not measured). When several municipality
   pins share a place they are spread apart so each can be selected, and the panel says so.
   Re-checking turned up two stale entries (both Amazon campuses were still listed as
   announced), which is why statuses carry dates and should be re-read periodically.

   **Neon sync (2026-10-15).** Pointing the pipeline straight at Neon was the original plan
   and was rejected after checking Neon's free-plan limits: 100 compute-hours per project per
   month, with compute suspending after 5 idle minutes. A pipeline that writes every 5
   minutes never lets Neon suspend, which is roughly 180 compute-hours a month, and when the
   allowance runs out Neon suspends and the site and the pipeline both stop. Instead,
   `scripts/sync_to_neon.py` (logic in `common/neon_sync.py`) runs hourly, first from a Windows
   scheduled task (`pa-grid-monitor-neon-sync`) and since 2026-10-16 from the VPS's cron
   (that task is disabled and must stay so, or two machines would write to Neon), so Neon
   sleeps between runs. Each run
   streams rows newer than Neon's newest timestamp (minus a 6-hour overlap, so revised or
   late rows are caught) into a temporary table and upserts them on the primary key, writing
   only rows whose values changed. A re-run is therefore harmless, and `--full` resends
   everything after a long outage. It reads `POSTGRES_DSN` (local) and `NEON_DIRECT_URL`
   (Neon's direct, unpooled URL), refuses a pooled URL, and applies any new migration to
   Neon first. The cost is that the website lags the pipeline by up to an hour. The website
   itself uses Neon's pooled URL, with prepared statements switched off for pooled URLs.
   Limits: the scheduled task only runs while this machine is on and signed in, and the
   pipeline processes themselves are started by hand, so after a restart Neon goes stale until
   both are running again.

   **Private-page audit and what it found (2026-10-15).** The private zone pages showed no
   forecast line and an empty residuals chart. Cause: `pjm_lmp_readings` had a two-day hole
   (Oct 13 and 14) from when the pipeline was not running, and `inference/pjm_service.py`
   correctly declines to score when the week of history before a reading has a hole. It logged
   that decision at DEBUG, so nothing visible said scoring had stopped. Fixes: the hole was
   closed with the verified feed (`python -m ingestion.backfill --source pjm`);
   `scripts/rescore_recent.py` re-scores the trailing days with `model.score.score_since`, a
   batch version of `score_latest` that a test pins to it point by point (and that reproduced
   the live EIA service's stored scores exactly on real data) so the stretch the live service
   skipped gets a forecast and residuals; and `inference/skip_tracker.py` now logs a WARNING
   once when scoring halts and an INFO when it resumes. Also corrected: the zone charts were
   labelled hourly but are 5-minute data, and the price chart gained a legend and a note that
   the newest prices are provisional. One thing to keep in mind when reading the result: the
   PJM detector flags about 3% of the last week's intervals against the 1% budget it was
   calibrated to on validation data. The week included a multi-hour price spike on Oct 13 and a
   very large one on Oct 14, and sustained spikes are flagged interval by interval, so some
   of that is expected, but the rate should be watched rather than assumed to be fine.

   **Private sign-in lockout (2026-10-15).** Three wrong passcodes lock a visitor out for 15
   minutes, and during the lockout even the correct passcode is refused. State is in the
   `private_login_attempts` table (migration 0004), keyed by a hash of the visitor's IP,
   because the site runs as serverless functions and an in-memory counter would reset between
   requests. It fails closed: if the table cannot be reached, nobody signs in. It limits
   guessing from one address only, so the passcode still needs to be long. The `next`
   redirect after sign-in is restricted to same-site `/private/` paths.

   **Local watchdog (2026-10-16).** The pipeline runs by hand on one Windows machine, and the
   two outages so far (a two-day hole on Oct 13 to 14, and a Kafka crash on Oct 15) were both
   the failure Section 7 predicts: something quietly stops and the site goes stale.
   `scripts/windows/watchdog.ps1` is a stopgap until the pipeline moves somewhere that
   restarts it. `install_watchdog.ps1` schedules it at logon and every two minutes. Each pass
   (1) starts Postgres and Kafka if they are down, (2) starts any of the eight pipeline
   processes that are missing, giving each its own metrics port because the code defaults
   them all to 9100, and restarts an inference service that fails its `/health` check three
   passes running, (3) reads data freshness from `scripts/pipeline_status.py` and checks the
   Neon sync task, and (4) once a day re-pulls the last four days from PJM's verified feed and
   EIA and re-scores them with `scripts/rescore_recent.py`. Step 4 is the real fix for the
   hole problem: the live PJM feed returns only the newest interval, so a missed stretch can
   only be recovered from the verified feed, and the scorer refuses to score across a hole.
   Stall thresholds are PJM LMP 25 minutes, EIA demand 8 hours and PJM load 4 days, chosen
   from the normal ages (a few minutes, about 2 to 6 hours, and 1 to 2 days). A stalled LMP
   stream also restarts the PJM poller, consumer and inference service, at most hourly. A
   process that needs more than five restarts in an hour stops being restarted and alerts
   instead. Alerts go to the log and a Windows notification, plus a phone push through
   ntfy.sh if `WATCHDOG_NTFY_TOPIC` is set in `.env`; each problem alerts once, repeats every
   three hours, and reports when it clears. Processes are created through WMI so Task
   Scheduler does not tear them down when the pass ends, which was checked by killing a
   process, letting the task restart it and confirming it survived. Killing Kafka outright
   was also tested: the next pass restarted it in about 20 seconds and the consumers
   reconnected. Limits: it only runs while the machine is on and signed in (the task is
   interactive, like the Neon sync), so sleep, a reboot without sign-in, or a power cut still
   stops everything until the machine is back, and it cannot alert while the machine is off.
   That limit is why the pipeline moved to a server the same day. The scheduled task was
   uninstalled at the cutover; the scripts stay in the repo for anyone running the pipeline
   by hand on Windows.

   **VPS deployment (2026-10-16).** The pipeline now runs on a rented VPS instead of the
   local machine (Contabo Cloud VPS 4: 4 vCPU, 8 GB RAM, Ubuntu 26.04, EU region, about $6.60
   a month), replacing the Oracle plan in Sections 2, 3 and 5, which stays unbuilt because
   Always Free capacity was unavailable. Everything is in `deploy/vps/`. The stack is the same
   services as the repo-root Compose file, with these differences: nothing is published to the
   host (Docker publishes ports around the host firewall, so a stray `ports:` line would put
   Postgres or Kafka on the internet), every service restarts on its own, logs are rotated,
   Postgres and Kafka use named volumes, and Prometheus and Grafana are gone because the
   website replaced them. Only SSH is reachable: key-only, behind a firewall and fail2ban.
   One bug the move would have caused is worth recording. PJM allows 6 requests a minute per
   key, and the clients enforce that with a lock file in the temp directory shared by every
   process on the host (`ingestion/pjm_poller/client.py`). Containers each have their own
   `/tmp`, so the LMP poller, the load poller and the gap heal would each have believed they
   had the whole allowance. Every container that calls PJM now sets `TMPDIR` to one shared
   volume, and the two pollers' zone calls were seen spaced about 33 seconds apart, so the
   limit is shared. Cron runs `ops.sh`: a check every five minutes (the Linux counterpart of
   the Windows watchdog, with the same stall limits), the hourly Neon sync, and the daily gap
   heal. Alerts reach the log, and optionally an ntfy.sh topic and a healthchecks.io
   heartbeat, the only signal that fires if the server itself dies; neither was configured at
   cutover, so a dead server is not yet noticed. The model artifacts are copied to the server
   by hand and mounted, never baked into an image. The cutover stopped the local pipeline,
   took a `pg_dump`, restored it (row counts matched exactly on all five tables), and
   started the server, because only one machine may poll PJM with the key at a time and the
   verified PJM feed reaches back only about six months, so the existing history had to be
   carried across rather than re-fetched. The local pipeline processes and Windows tasks are
   stopped; local Postgres and Kafka were left running for a day as a way back.

   Seven hours after the cutover all ten containers were up and the four healthcheck-bearing
   ones healthy, the newest PJM LMP interval was 10 minutes old, the hourly sync had run on
   schedule from the server, and the machine had 9.5 GB of 96 GB disk and about 6 GB of
   memory free. The first scheduled daily heal (12:15 UTC) had not yet run, so cron-driven
   gap healing is untested; the one heal that has run was started by hand after the cutover.
   **CI replay test (2026-10-16).** The kind job used to prove only that the images start and
   report healthy. It now also pushes a synthetic scenario through the real path, in the
   cluster: `scripts/replay/drive.py` loads a week of history into Postgres as a backfill
   would, then publishes 48 hours (534 intervals) to Kafka one at a time, and asserts on what
   comes out. The scenario (`scripts/replay/data.py`) is made up, a daily cycle with bounded
   noise for one zone, because CI carries no PJM data and makes no live calls. Planted in it
   are a spike up, a spike down, a 3-hour stuck-sensor stretch and a 3.5-hour outage during
   which nothing is published. The checks: every published interval is stored with the
   published price; the outage leaves a hole and nothing fills it; the isolation forest flags
   exactly the two spikes; the stuck-sensor rule flags exactly the flat stretch from the point
   its run is long enough; exactly the 12 intervals after the outage are declined and all
   others scored; `scoring_runs_total` and `anomalies_flagged_total` equal what is in the
   database; and re-publishing a block of intervals changes no price, score or flag. The
   artifact it loads is fitted on the clean version of the same series with the threshold just
   above the highest training score, so the only legitimate flags are the planted ones. That
   makes it a test of the plumbing, not of detector quality. The driver publishes one interval
   at a time and waits for it to land in Postgres, because the inference service reads its
   history back from there and a real poller is five minutes apart; the PJM consumer's batch
   wait is set to zero for the run through `PJM_CONSUMER_BATCH_WAIT_SECONDS`. The same
   scenario is also scored offline in `tests/test_replay_scenario.py`, so a bad scenario fails
   in seconds before a cluster is built.

   What it found. Designing the outage exposed a real bug in the serving path. Both inference
   services, and the daily heal, removed excluded (too-long-gap) periods from the series
   before computing the seasonal-naive forecast, which shifts by row count. After any hole
   longer than the forward fill, "same time last week" therefore pointed at a different time
   of day, and the residual measured the wrong thing. On a noise-free series whose true
   residual is zero, a 20-interval hole 100 intervals earlier gave a residual of -4.65.
   Excluded periods now stay in the series as NaN, so a point whose week-ago reading or recent
   window is missing comes back with a null residual and is declined instead. Replayed
   against the old service code, the scenario declined 102 intervals after the outage instead
   of 12. Two things are not changed and should be known: `model/train.py` and the evaluation
   scripts still drop excluded rows before shifting, so the artifacts were fitted on residuals
   that are slightly off near holes (retraining would remove that), and the fix is in the
   repository but not yet running on the VPS. A second, smaller finding: `score_since`, which
   the heal uses, is documented as equivalent to scoring each point live, but the flatline rule
   measures a whole run, so in batch it also flags the first 11 rows of a stuck stretch that
   live scoring flagged only later. That difference is now pinned by a test and described in the
   docstring rather than changed.

   The first run of the replay in CI found a third problem before it got as far as scoring: the
   Kafka StatefulSet in `infra/k8s` never became Ready. Its probes ran
   `kafka-broker-api-versions.sh`, which starts a JVM each time and exceeds a probe's default
   one-second timeout on a small node, so the pod stayed unready and the liveness probe kept
   killing the broker. Fixing the probes exposed the cause underneath: the broker must resolve
   its own name (`kafka`, its advertised address and controller voter) to start, and a headless
   Service publishes DNS only for Ready pods, so it died with UnknownHostException before it
   could ever become Ready. The earlier kind job did not notice because nothing in it needed
   Kafka reachable; the manifests had been called "verified against a real cluster" while the
   broker was crash-looping. The Service now sets `publishNotReadyAddresses`, the probes are
   TCP checks with a startup probe, and the job waits for `kafka-0` to be Ready before the
   replay.

   **Pipeline health page.** `/private/pipeline` shows whether the pipeline is delivering,
   because the website reads only the Neon copy and a dead server otherwise looks the same as
   a quiet one. After each hourly sync, `scripts/sync_to_neon.py` writes one row to
   `pipeline_health` (migration 0005, `common/health.py`): per stream, the newest reading and
   its age against the watchdog's limit; per table, rows on the server against rows in Neon;
   and the host's state (services running, failing health checks, open alerts, last
   five-minute check and daily heal, uptime, disk), which `ops.sh` passes in as JSON. Only
   timestamps, counts and states are stored, never values. The page ages each stream forward
   from the report and treats a report older than 2.5 hours as the headline, which makes it the
   check a human can make without the server: if the page says the last report was hours ago,
   the sync failed or the machine is down. A failed snapshot write does not fail the sync.
   The daily completeness chart is counted from the copied readings instead (share of expected
   5-minute intervals and hours present, per day), so it has history from day one. The newest
   day of EIA and the newest two days of PJM load are left out because those feeds publish
   late. Limits: reports are hourly, and the pollers' Prometheus counters and scoring latency
   are not collected, since Prometheus does not run on the server.

   Open items: no alert channel is configured, about 12% of live 5-minute PJM intervals were
   missing when last counted (the cause was not investigated; the verified feed and the daily
   heal are meant to fill them), and the EIA key appeared in a terminal during setup and
   should be regenerated if that output is retained anywhere.

## 10. Steps to complete before building starts

These are the only external dependencies: everything else (Kafka, Postgres, Grafana, k3s,
Docker, GitHub Actions) is self-installed later and needs no advance signup.

1. **EIA API key** (done): obtained and saved securely (not in the repo).
2. **PJM Tools account created** (done): via `accountmanager.pjm.com` / `apiportal.pjm.com`.
   This alone does not grant API access; the provisioning email in step 3 is what does.
3. **Non-member provisioning email sent** (done) to `accountmanager@pjm.com`, and **access
   confirmed live** (2026-10-13): a plain `Ocp-Apim-Subscription-Key` successfully
   authenticates against real Data Miner 2 endpoints. The private tier is unblocked.
4. **PKI-certificate auth checked** (done): not required. The plain subscription key above
   authenticated without one, confirmed live against `api.pjm.com` (Section 3 has the
   detail). Revisit only if auth starts failing later.
5. **Oracle Cloud account**: superseded by the VPS (Section 9, "VPS deployment"); the notes
   below apply only if an Oracle VM is ever created. Once the VM exists: reserve a Public IPv4 address
   (Always Free allows 2 at no cost) and attach it, rather than leaving the default ephemeral
   IP in place.
6. **GitHub repo created** (done): `github.com/aaaaaron29/pa-grid-monitor`, architecture doc
   pushed.
7. **Register a free subdomain** (e.g. via DuckDNS) pointed at the Oracle VM's eventual
   reserved IP; needed for the TLS/public-access plan in Section 5. Can be done anytime
   before Phase 5 deploy, no rush.

No external dependency remains. PJM access is confirmed and live, so the private tier is unblocked too:
remaining PJM work is the zone-identifier confirmation and feed-strategy implementation
noted in Section 3/4, not an access/provisioning wait.
