import { createHash } from "crypto";
import { headers } from "next/headers";
import { sql } from "@/lib/db";

// Three wrong passcodes lock a visitor out for fifteen minutes. State lives in the database
// (infra/sql/0004_login_attempts.sql) because the site runs as serverless functions, where
// an in-memory counter would be reset by every new instance.
//
// What this does and does not stop: it rate-limits guessing from one address. A guesser who
// rotates addresses is not slowed, so the passcode itself still has to be long.

export const MAX_FAILURES = 3;
export const LOCK_MINUTES = 15;

/** Hash of the caller's IP. On Vercel the platform sets x-forwarded-for; locally there is none,
 *  so every local visitor shares one bucket, which is fine for development. */
export async function clientKey(): Promise<string> {
  const h = await headers();
  const forwarded = h.get("x-forwarded-for")?.split(",")[0]?.trim();
  const ip = forwarded || h.get("x-real-ip") || "unknown";
  return createHash("sha256").update(`gw-client:${ip}`).digest("hex");
}

/** Whole minutes left on an active lockout, or 0 when the visitor is not locked out. */
export async function lockedMinutes(key: string): Promise<number> {
  const rows = await sql<{ minutes: number }[]>`
    SELECT ceil(extract(epoch FROM (locked_until - now())) / 60)::int AS minutes
    FROM private_login_attempts
    WHERE client_key = ${key} AND locked_until > now()
  `;
  return rows[0]?.minutes ?? 0;
}

/** Count one wrong guess. Starts a fresh window if the last one is older than the lockout
 *  length, and starts the lockout when the limit is reached. One statement does the counting
 *  so two simultaneous guesses cannot both slip under the limit. */
export async function recordFailure(key: string): Promise<{ failures: number; locked: boolean }> {
  const rows = await sql<{ failures: number }[]>`
    INSERT INTO private_login_attempts AS a (client_key, failures, window_start, locked_until)
    VALUES (${key}, 1, now(), NULL)
    ON CONFLICT (client_key) DO UPDATE SET
      failures = CASE WHEN a.window_start < now() - make_interval(mins => ${LOCK_MINUTES})
                      THEN 1 ELSE a.failures + 1 END,
      locked_until = CASE WHEN a.window_start < now() - make_interval(mins => ${LOCK_MINUTES})
                          THEN NULL ELSE a.locked_until END,
      window_start = CASE WHEN a.window_start < now() - make_interval(mins => ${LOCK_MINUTES})
                          THEN now() ELSE a.window_start END
    RETURNING failures
  `;
  const failures = rows[0].failures;
  if (failures >= MAX_FAILURES) {
    await sql`
      UPDATE private_login_attempts
      SET locked_until = now() + make_interval(mins => ${LOCK_MINUTES})
      WHERE client_key = ${key}
    `;
    return { failures, locked: true };
  }
  return { failures, locked: false };
}

/** A successful sign-in wipes the record, so earlier typos do not count against the visitor. */
export async function clearFailures(key: string): Promise<void> {
  await sql`DELETE FROM private_login_attempts WHERE client_key = ${key}`;
}
