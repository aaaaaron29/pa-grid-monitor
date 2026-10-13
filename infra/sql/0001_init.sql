-- Phase 1 schema: raw storage for all three ingestion sources named in
-- Architecture.md Section 9 Phase 1 ("Postgres schema for all three"). Only the
-- eia_readings writer (poller + backfill) ships in this phase; pjm_lmp_readings and
-- interconnection_queue are created now so the PJM poller and queue scraper have a
-- stable target to write to once they're built, without a schema-change PR blocking them.
--
-- Derived tables (eia_forecasts, zone_stress_vs_dc) belong to later migrations, once
-- their producers (the forecast CronJob, the correlation join job) actually exist —
-- Architecture.md Section 6/7 specs their columns; adding the tables before anything
-- writes to them just invites schema drift between this file and that spec.
--
-- All timestamps are timestamptz in UTC, interval-beginning (Architecture.md Section 7).
-- Applied by scripts/apply_migrations.py, in filename order, tracked in schema_migrations.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Public tier: EIA-930 hourly BA-level demand / net generation / total interchange for PJM.
CREATE TABLE IF NOT EXISTS eia_readings (
    respondent      text NOT NULL,                 -- EIA Balancing Authority code, e.g. 'PJM'
    reading_type    text NOT NULL CHECK (reading_type IN ('D', 'NG', 'TI')),
                                                     -- D = demand, NG = net generation, TI = total interchange
    period_start    timestamptz NOT NULL,           -- UTC, hour-beginning
    value_mw        double precision,               -- NULL when EIA reports no value for the hour
    quality         text NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok', 'missing')),
    retrieved_at    timestamptz NOT NULL,            -- when this value was last fetched (revision tracking)
    PRIMARY KEY (respondent, reading_type, period_start)
);

CREATE INDEX IF NOT EXISTS eia_readings_period_idx ON eia_readings (period_start);

-- Private tier: PJM Data Miner 2 real-time LMP, PA zones only. Writer: pjm_poller (not yet
-- built — Section 10 PKI/provisioning check is still outstanding).
CREATE TABLE IF NOT EXISTS pjm_lmp_readings (
    zone            text NOT NULL,                 -- PECO | PPL | METED | PENELEC | DUQ
    period_start    timestamptz NOT NULL,           -- UTC, 5-minute interval start
    lmp_price       double precision,               -- $/MWh; NULL on a reporting gap
    quality         text NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok', 'missing')),
    retrieved_at    timestamptz NOT NULL,
    PRIMARY KEY (zone, period_start)
);

CREATE INDEX IF NOT EXISTS pjm_lmp_readings_period_idx ON pjm_lmp_readings (period_start);

-- Private tier: Large Load Registry / interconnection-queue snapshots. Stored as
-- slowly-changing records, never overwritten in place (Architecture.md Section 6) — without
-- point-in-time reconstruction you can't say what the queue looked like when a given
-- month's grid stress actually occurred. Writer: queue_scraper (source TBD, Phase 1).
CREATE TABLE IF NOT EXISTS interconnection_queue (
    snapshot_date   date NOT NULL,                  -- date this snapshot was published/scraped
    project_id      text NOT NULL,                  -- source's own project/queue identifier
    zone            text,                            -- PA zone if determinable, else NULL
    mw              double precision,
    status          text,                            -- source's own status string, stored as-is
    retrieved_at    timestamptz NOT NULL,
    PRIMARY KEY (snapshot_date, project_id)
);

INSERT INTO schema_migrations (version) VALUES ('0001_init')
ON CONFLICT (version) DO NOTHING;
