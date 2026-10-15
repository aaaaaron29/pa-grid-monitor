-- Failed-passcode tracking for the website's private area (frontend/src/lib/lockout.ts).
-- Lives in the database rather than server memory because the site runs as serverless
-- functions: consecutive requests can land on different instances, so an in-memory counter
-- would never reach its limit. The key is a hash of the visitor's IP address, never the
-- address itself. This is website state, not pipeline data, so scripts/sync_to_neon.py does
-- not copy it.
CREATE TABLE IF NOT EXISTS private_login_attempts (
    client_key    text PRIMARY KEY,                -- sha256 of the client IP
    failures      integer NOT NULL DEFAULT 0,      -- wrong guesses in the current window
    window_start  timestamptz NOT NULL DEFAULT now(),
    locked_until  timestamptz                      -- NULL, or the time the lockout ends
);

INSERT INTO schema_migrations (version) VALUES ('0004_login_attempts')
ON CONFLICT (version) DO NOTHING;
