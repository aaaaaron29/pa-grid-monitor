-- One row per hourly sync: how the pipeline looked from the server's side at that moment
-- (data freshness, how many rows the website copy is behind, host and cron state). The
-- private pipeline page reads this, because the website can see only the Neon copy and a
-- dead server would otherwise look the same as a quiet one. No PJM values are stored here,
-- only timestamps, counts and states.
CREATE TABLE IF NOT EXISTS pipeline_health (
    captured_at  timestamptz PRIMARY KEY,
    payload      jsonb NOT NULL
);

INSERT INTO schema_migrations (version) VALUES ('0005_pipeline_health')
ON CONFLICT (version) DO NOTHING;
