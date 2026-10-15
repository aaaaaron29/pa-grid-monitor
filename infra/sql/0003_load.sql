-- PJM hrl_load_metered: real zone-level metered demand (MW), confirmed live 2026-10-14 (see
-- Architecture.md's data center accountability section). Separate table from
-- pjm_lmp_readings deliberately: different feed, different cadence (this one posts once
-- daily, not every 5 minutes), different revision window (values can be revised for up to
-- 90 days per the feed's own metadata, not settled next-day like LMP).
--
-- The feed's own zone codes (PE, PL, ME, PN, DUQ) are not the project's zone names -- PE/PL/
-- ME/PN map to PECO/PPL/METED/PENELEC respectively; DUQ matches directly. PPL's feed zone
-- ("PL") further splits into two load_area components (PLCO + UGI) that must be summed to
-- get one PPL-zone total; this table stores only the already-summed per-zone total, not the
-- raw load_area breakdown, matching pjm_lmp_readings' one-row-per-zone-per-interval shape.
CREATE TABLE IF NOT EXISTS pjm_load_readings (
    zone            text NOT NULL,                 -- PECO | PPL | METED | PENELEC | DUQ
    period_start    timestamptz NOT NULL,           -- UTC, hour-beginning
    load_mw         double precision,               -- summed across the feed's load_area rows
    quality         text NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok', 'missing')),
    verified        boolean NOT NULL DEFAULT false, -- true only once every constituent
                                                     -- load_area row the feed returned for
                                                     -- this zone/interval is itself verified
    retrieved_at    timestamptz NOT NULL,
    PRIMARY KEY (zone, period_start)
);

CREATE INDEX IF NOT EXISTS pjm_load_readings_period_idx ON pjm_load_readings (period_start);

-- Record this migration like the others do, so the runner skips it next time. (It was
-- previously re-applied on every run; harmless because everything above is IF NOT EXISTS.)
INSERT INTO schema_migrations (version) VALUES ('0003_load')
ON CONFLICT (version) DO NOTHING;
