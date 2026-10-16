import { sql } from "@/lib/db";

// Pipeline health for /private/pipeline. Two sources: the snapshot the server writes to Neon
// after every hourly sync (common/health.py), and completeness counted directly from the
// copied readings. Counts, timestamps and states only; no PJM values are read here, though the
// page stays behind the passcode like the rest of /private.

export interface StreamSnapshot {
  label: string;
  newest: string | null;
  age_minutes: number | null;
  limit_minutes: number;
  normal: string;
}

export interface SyncTable {
  table: string;
  rows_written: number;
  source_count: number;
  destination_count: number;
  seconds: number;
}

export interface HostSnapshot {
  services_expected: number;
  services_running: number;
  services_unhealthy: number;
  open_alerts: string[];
  heal_days: number;
  uptime_seconds: number;
  disk_used_percent: number;
  last_watch_at: string | null;
  last_heal_at: string | null;
}

export interface HealthSnapshot {
  capturedAt: string;
  /** Minutes since the report, by the database's clock so the page needs no clock of its own. */
  ageMinutes: number;
  streams: Record<string, StreamSnapshot>;
  sync: SyncTable[];
  host: HostSnapshot | null;
}

interface RawSnapshot {
  streams?: Record<string, StreamSnapshot>;
  sync?: SyncTable[];
  host?: HostSnapshot | null;
}

// The table is created by the first sync that runs after the migration ships, which can be a
// few minutes after the page does. Until then the page shows its "not reported yet" state.
async function rowsOrNone<R>(query: PromiseLike<R[]>): Promise<R[]> {
  try {
    return await query;
  } catch (err) {
    if ((err as { code?: string }).code === "42P01") return [];
    throw err;
  }
}

export async function getLatestSnapshot(): Promise<HealthSnapshot | null> {
  const rows = await rowsOrNone(sql<{ captured_at: Date; age: number; payload: RawSnapshot }[]>`
    SELECT captured_at, extract(epoch from (now() - captured_at)) / 60 AS age, payload FROM pipeline_health ORDER BY captured_at DESC LIMIT 1
  `);
  const row = rows[0];
  if (!row) return null;
  return {
    capturedAt: row.captured_at.toISOString(),
    ageMinutes: Number(row.age),
    streams: row.payload.streams ?? {},
    sync: row.payload.sync ?? [],
    host: row.payload.host ?? null,
  };
}

export type AgePoint = {
  t: string;
  pjmPrices: number | null;
  pjmScored: number | null;
};

/** Age of the PJM price stream at each hourly snapshot, oldest first. */
export async function getAgeHistory(days = 7): Promise<AgePoint[]> {
  const rows = await rowsOrNone(sql<{ t: Date; prices: string | null; scored: string | null }[]>`
    SELECT captured_at AS t,
           payload #>> '{streams,pjm_lmp,age_minutes}' AS prices,
           payload #>> '{streams,pjm_lmp_scored,age_minutes}' AS scored
    FROM pipeline_health
    WHERE captured_at > now() - make_interval(days => ${days}::int)
    ORDER BY captured_at
  `);
  return rows.map((r) => ({
    t: r.t.toISOString(),
    pjmPrices: r.prices === null ? null : Number(r.prices),
    pjmScored: r.scored === null ? null : Number(r.scored),
  }));
}

export type CompletenessPoint = {
  t: string; // UTC day start, ISO
  prices: number | null; // percent of expected 5-minute intervals present
  scored: number | null; // percent of expected intervals that have been scored
  eia: number | null; // percent of expected hours present
  load: number | null;
};

const ZONE_COUNT = 5;
const PRICE_INTERVAL_MIN = 5;
// EIA publishes hours late and PJM metered load a day or two late, so the newest days of those
// feeds are incomplete by design, not by failure. They are left out rather than drawn as a dip.
const EIA_SKIP_DAYS = 1;
const LOAD_SKIP_DAYS = 2;

const pct = (n: number, expected: number) =>
  expected <= 0 ? null : Math.min(100, Math.round((n / expected) * 1000) / 10);

export async function getCompleteness(days = 21): Promise<CompletenessPoint[]> {
  const [prices, scored, eia, load] = await Promise.all([
    sql<{ day: string; n: number }[]>`
      SELECT to_char(period_start AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day, count(*)::int AS n
      FROM pjm_lmp_readings
      WHERE quality = 'ok' AND lmp_price IS NOT NULL
        AND period_start >= (date_trunc('day', now() AT TIME ZONE 'UTC') - make_interval(days => ${days - 1}::int)) AT TIME ZONE 'UTC'
      GROUP BY 1`,
    sql<{ day: string; n: number }[]>`
      SELECT to_char(period_start AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day, count(*)::int AS n
      FROM pjm_lmp_anomalies
      WHERE period_start >= (date_trunc('day', now() AT TIME ZONE 'UTC') - make_interval(days => ${days - 1}::int)) AT TIME ZONE 'UTC'
      GROUP BY 1`,
    sql<{ day: string; n: number }[]>`
      SELECT to_char(period_start AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day, count(*)::int AS n
      FROM eia_readings
      WHERE reading_type = 'D' AND quality = 'ok'
        AND period_start >= (date_trunc('day', now() AT TIME ZONE 'UTC') - make_interval(days => ${days - 1}::int)) AT TIME ZONE 'UTC'
      GROUP BY 1`,
    sql<{ day: string; n: number }[]>`
      SELECT to_char(period_start AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day, count(*)::int AS n
      FROM pjm_load_readings
      WHERE quality = 'ok'
        AND period_start >= (date_trunc('day', now() AT TIME ZONE 'UTC') - make_interval(days => ${days - 1}::int)) AT TIME ZONE 'UTC'
      GROUP BY 1`,
  ]);

  const byDay = (rows: { day: string; n: number }[]) => new Map(rows.map((r) => [r.day, r.n]));
  const p = byDay(prices);
  const sc = byDay(scored);
  const e = byDay(eia);
  const l = byDay(load);

  const now = new Date();
  const todayStart = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  // Scoring began part-way through some day; that day is a ramp, not a failure, so the series
  // starts on the day after.
  const firstScoredDay = [...sc.entries()].filter(([, n]) => n > 0).map(([d]) => d).sort()[0];
  const firstScored = firstScoredDay
    ? new Date(Date.parse(firstScoredDay) + 86_400_000).toISOString().slice(0, 10)
    : undefined;

  const out: CompletenessPoint[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const start = todayStart - i * 86_400_000;
    const day = new Date(start).toISOString().slice(0, 10);
    // For today only the intervals that have already happened can be expected.
    const elapsedMin = Math.min(1440, (now.getTime() - start) / 60_000);
    const priceExpected = ZONE_COUNT * Math.floor(elapsedMin / PRICE_INTERVAL_MIN);
    const hoursExpected = 24;
    out.push({
      t: new Date(start).toISOString(),
      prices: pct(p.get(day) ?? 0, priceExpected),
      // Days before scoring began are not drawn as zero.
      scored: firstScored && day >= firstScored ? pct(sc.get(day) ?? 0, priceExpected) : null,
      eia: i >= EIA_SKIP_DAYS ? pct(e.get(day) ?? 0, hoursExpected) : null,
      load: i >= LOAD_SKIP_DAYS ? pct(l.get(day) ?? 0, hoursExpected * ZONE_COUNT) : null,
    });
  }
  return out;
}
