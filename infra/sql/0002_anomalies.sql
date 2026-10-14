-- Phase 3 schema: anomaly scoring results, written by the FastAPI inference services
-- (one per tier). Architecture.md Section 5's diagram shows the inference service writing
-- down to Postgres alongside the forecast CronJob -- this is that write target.
--
-- Deliberately stores BOTH the raw score and the flag, per detection method (isolation
-- forest vs the flatline rule), not just a single blended boolean -- Section 6's whole
-- evaluation story is built on being able to say *why* something was flagged, and
-- collapsing that into one bit would throw away exactly the information the dashboard's
-- "Forecast residuals" panel (Section 5) needs to show.

CREATE TABLE IF NOT EXISTS eia_anomalies (
    period_start        timestamptz NOT NULL,
    reading_type        text NOT NULL CHECK (reading_type IN ('D', 'NG', 'TI')),
    residual            double precision,
    forest_score        double precision,          -- higher = more anomalous (Detector's own convention)
    forest_flagged      boolean NOT NULL DEFAULT false,
    flatline_flagged    boolean NOT NULL DEFAULT false,
    scored_at           timestamptz NOT NULL,
    PRIMARY KEY (period_start, reading_type)
);

CREATE INDEX IF NOT EXISTS eia_anomalies_flagged_idx
    ON eia_anomalies (period_start)
    WHERE forest_flagged OR flatline_flagged;

CREATE TABLE IF NOT EXISTS pjm_lmp_anomalies (
    zone                text NOT NULL,
    period_start        timestamptz NOT NULL,
    residual            double precision,
    forest_score        double precision,
    forest_flagged      boolean NOT NULL DEFAULT false,
    flatline_flagged    boolean NOT NULL DEFAULT false,
    scored_at           timestamptz NOT NULL,
    PRIMARY KEY (zone, period_start)
);

CREATE INDEX IF NOT EXISTS pjm_lmp_anomalies_flagged_idx
    ON pjm_lmp_anomalies (zone, period_start)
    WHERE forest_flagged OR flatline_flagged;

INSERT INTO schema_migrations (version) VALUES ('0002_anomalies')
ON CONFLICT (version) DO NOTHING;
