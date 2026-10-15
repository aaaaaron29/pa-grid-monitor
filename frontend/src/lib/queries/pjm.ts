import { sql } from "@/lib/db";

// Ports of infra/grafana/provisioning/dashboards/private_pjm.json's panel queries, plus
// the PPL load-growth numbers behind docs/index.html's accountability section. PJM Data
// Miner 2 sourced (LMP, load) -- private-only, never reachable from a public route. See
// ARCHITECTURE.md Section 9 item 7.

export const ZONES = ["PECO", "PPL", "METED", "PENELEC", "DUQ"] as const;
export type Zone = (typeof ZONES)[number];

export interface ZoneSummary {
  currentPrice: number | null;
  peak24hPrice: number | null;
  freshnessSeconds: number | null;
  anomalies7d: number;
}

export async function getZoneSummary(zone: Zone): Promise<ZoneSummary> {
  const [current, peak, freshness, anomalies] = await Promise.all([
    sql<{ lmp_price: number }[]>`
      SELECT lmp_price FROM pjm_lmp_readings
      WHERE zone = ${zone} AND quality != 'missing'
      ORDER BY period_start DESC LIMIT 1
    `,
    sql<{ max: number }[]>`
      SELECT max(lmp_price) AS max FROM pjm_lmp_readings
      WHERE zone = ${zone} AND period_start > now() - interval '24 hours'
    `,
    sql<{ seconds: number }[]>`
      SELECT extract(epoch from (now() - max(period_start))) AS seconds
      FROM pjm_lmp_readings WHERE zone = ${zone}
    `,
    sql<{ count: number }[]>`
      SELECT count(*)::int AS count FROM pjm_lmp_anomalies
      WHERE zone = ${zone} AND (forest_flagged OR flatline_flagged)
        AND scored_at > now() - interval '7 days'
    `,
  ]);

  return {
    currentPrice: current[0]?.lmp_price ?? null,
    peak24hPrice: peak[0]?.max ?? null,
    freshnessSeconds: freshness[0]?.seconds ?? null,
    anomalies7d: anomalies[0]?.count ?? 0,
  };
}

export async function getAllZoneAnomalyCounts(): Promise<{ zone: string; count: number }[]> {
  const rows = await sql<{ zone: string; count: number }[]>`
    SELECT zone, count(*)::int AS count FROM pjm_lmp_anomalies
    WHERE (forest_flagged OR flatline_flagged) AND scored_at > now() - interval '7 days'
    GROUP BY zone ORDER BY zone
  `;
  return rows;
}

export interface LmpPoint {
  t: string;
  actual: number | null;
  forecast: number | null;
  flagged: boolean;
  [key: string]: unknown;
}

export async function getLmpVsForecast(zone: Zone, days = 7): Promise<LmpPoint[]> {
  const rows = await sql<
    { time: Date; actual: number; forecast: number | null; forest_flagged: boolean | null }[]
  >`
    SELECT r.period_start AS time, r.lmp_price AS actual,
      r.lmp_price - a.residual AS forecast, a.forest_flagged
    FROM pjm_lmp_readings r
    LEFT JOIN pjm_lmp_anomalies a ON a.period_start = r.period_start AND a.zone = r.zone
    WHERE r.zone = ${zone} AND r.period_start > now() - (${days} || ' days')::interval
    ORDER BY r.period_start
  `;
  return rows.map((r) => ({
    t: r.time.toISOString(),
    actual: r.actual,
    forecast: r.forecast,
    flagged: Boolean(r.forest_flagged),
  }));
}

export async function getZoneResiduals(zone: Zone, days = 7) {
  const rows = await sql<{ time: Date; residual: number; forest_flagged: boolean | null }[]>`
    SELECT period_start AS time, residual, forest_flagged
    FROM pjm_lmp_anomalies
    WHERE zone = ${zone} AND period_start > now() - (${days} || ' days')::interval
    ORDER BY period_start
  `;
  return rows.map((r) => ({
    t: r.time.toISOString(),
    residual: r.residual,
    flagged: Boolean(r.forest_flagged),
  }));
}

export interface ZoneAnomalyLogRow {
  time: string;
  residualPrice: number;
  forestScore: number | null;
  forestFlagged: boolean;
  flatlineFlagged: boolean;
  scoredAt: string;
}

export async function getZoneAnomalyLog(zone: Zone, limit = 100): Promise<ZoneAnomalyLogRow[]> {
  const rows = await sql<
    {
      time: Date;
      residual: number;
      forest_score: number | null;
      forest_flagged: boolean;
      flatline_flagged: boolean;
      scored_at: Date;
    }[]
  >`
    SELECT period_start AS time, residual, forest_score, forest_flagged, flatline_flagged, scored_at
    FROM pjm_lmp_anomalies
    WHERE zone = ${zone} AND (forest_flagged OR flatline_flagged)
    ORDER BY period_start DESC LIMIT ${limit}
  `;
  return rows.map((r) => ({
    time: r.time.toISOString(),
    residualPrice: r.residual,
    forestScore: r.forest_score,
    forestFlagged: r.forest_flagged,
    flatlineFlagged: r.flatline_flagged,
    scoredAt: r.scored_at.toISOString(),
  }));
}

// --- The PPL promises-vs-measured-load content (docs/index.html's accountability
// section), made live instead of a hardcoded snapshot. ---

export interface MonthlyLoadPoint {
  month: string; // "YYYY-MM"
  avgMw: number;
  peakMw: number;
  [key: string]: unknown;
}

export async function getPplMonthlyLoad(): Promise<MonthlyLoadPoint[]> {
  const rows = await sql<{ month: string; avg_mw: number; peak_mw: number }[]>`
    SELECT to_char(date_trunc('month', period_start), 'YYYY-MM') AS month,
      avg(load_mw)::numeric(10,1) AS avg_mw, max(load_mw)::numeric(10,1) AS peak_mw
    FROM pjm_load_readings
    WHERE zone = 'PPL' AND quality = 'ok'
    GROUP BY 1 ORDER BY 1
  `;
  return rows.map((r) => ({ month: r.month, avgMw: Number(r.avg_mw), peakMw: Number(r.peak_mw) }));
}

export interface YearOverYearLoad {
  year: number;
  avgMw: number;
  peakMw: number;
}

// Jan-through-"today's day-of-year" comparison across years, so a partial current year
// compares fairly against the same calendar window in prior years (matches the manual
// analysis behind docs/index.html's +3%/+4% figures).
export async function getPplLoadYearOverYear(): Promise<YearOverYearLoad[]> {
  const rows = await sql<{ yr: number; avg_mw: number; peak_mw: number }[]>`
    SELECT extract(year from period_start)::int AS yr,
      avg(load_mw)::numeric(10,0) AS avg_mw, max(load_mw)::numeric(10,0) AS peak_mw
    FROM pjm_load_readings
    WHERE zone = 'PPL' AND quality = 'ok'
      AND extract(doy from period_start) <= extract(doy from now())
    GROUP BY 1 ORDER BY 1
  `;
  return rows.map((r) => ({ year: r.yr, avgMw: Number(r.avg_mw), peakMw: Number(r.peak_mw) }));
}
