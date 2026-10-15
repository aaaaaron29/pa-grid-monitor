# pa-grid-monitor

Near-real-time anomaly detection on the PJM electricity grid, with a private analysis layer
correlating zone-level grid stress in Pennsylvania against data-center interconnection activity.

**Status: core pipeline built and CI-verified end to end (ingestion, Kafka, Postgres, both inference services, Prometheus, Grafana, and Kubernetes manifests validated against a real cluster in CI). The data-center correlation layer and a dedicated frontend are deferred, not built.

## What it does

Polls grid data on a schedule into Kafka and Postgres, forecasts what demand should be,
flags the intervals where reality diverges from that forecast, and serves the result from a
Grafana dashboard running 24/7 on a self-hosted k3s cluster.

"Near-real-time" is literal: EIA publishes on a multi-hour lag and PJM refreshes every five
minutes, so this is scheduled polling, not a continuous event stream.

## Two data tiers, and why

|  | Public tier | Private tier |
|---|---|---|
| **Source** | EIA-930 Hourly Electric Grid Monitor | PJM Data Miner 2 |
| **Granularity** | PJM-wide, hourly | PA zones (PECO, PPL, METED, PENELEC, DUQ), 5-minute |
| **Visibility** | Open dashboard link | Authenticated access only |

PJM's Data Miner terms prohibit non-members from republishing its data, so everything
publicly visible here (the dashboard and this repository) is built exclusively on EIA's
U.S. federal public-domain data. The PJM tier exists for zone-level analysis and is
demonstrated live rather than published: **no raw PJM values, sample rows, screenshots, or
PJM-trained model artifacts appear in this repo.** Code, schema, methodology, and aggregate
findings do.

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

## Stack

Python · Kafka (KRaft) · Postgres · scikit-learn / PyTorch · FastAPI · Prometheus · Grafana ·
k3s on Oracle Cloud · GitHub Actions
