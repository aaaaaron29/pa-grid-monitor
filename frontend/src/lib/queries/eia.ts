import { sql } from "@/lib/db";

// Ports of infra/grafana/provisioning/dashboards/public_eia.json's panel queries.
// EIA-930 sourced, federal and unrestricted -- safe for public routes (see
// ARCHITECTURE.md Section 9 item 7 on why this distinction matters here).
//
// Grafana's queries multiply value_mw by 1_000_000 to convert MW -> W so its stat
// panels' "watt" unit can SI-auto-prefix the display (e.g. "94.3 GW"). That was
// Grafana-specific display plumbing, not a unit the data is actually stored in --
// eia_readings.value_mw is already real megawatts (matches docs/index.html's existing
// DEMAND snapshot values, e.g. ~94274 for PJM-wide demand). This app formats MW directly
// instead and drops that multiplier.

export interface EiaSummary {
  currentMw: number | null;
  peak24hMw: number | null;
  freshnessSeconds: number | null;
  anomalies7d: number;
}

export async function getEiaReadingCount(): Promise<number> {
  const rows = await sql<{ count: number }[]>`SELECT count(*)::int AS count FROM eia_readings`;
  return rows[0]?.count ?? 0;
}

export async function getEiaSummary(): Promise<EiaSummary> {
  const [current, peak, freshness, anomalies] = await Promise.all([
    sql<{ value_mw: number }[]>`
      SELECT value_mw FROM eia_readings
      WHERE respondent = 'PJM' AND reading_type = 'D' AND quality != 'missing'
      ORDER BY period_start DESC LIMIT 1
    `,
    sql<{ max: number }[]>`
      SELECT max(value_mw) AS max FROM eia_readings
      WHERE respondent = 'PJM' AND reading_type = 'D'
        AND period_start > now() - interval '24 hours'
    `,
    sql<{ seconds: number }[]>`
      SELECT extract(epoch from (now() - max(period_start))) AS seconds
      FROM eia_readings WHERE respondent = 'PJM' AND reading_type = 'D'
    `,
    sql<{ count: number }[]>`
      SELECT count(*)::int AS count FROM eia_anomalies
      WHERE reading_type = 'D' AND (forest_flagged OR flatline_flagged)
        AND scored_at > now() - interval '7 days'
    `,
  ]);

  return {
    currentMw: current[0]?.value_mw ?? null,
    peak24hMw: peak[0]?.max ?? null,
    freshnessSeconds: freshness[0]?.seconds ?? null,
    anomalies7d: anomalies[0]?.count ?? 0,
  };
}

export interface DemandPoint {
  t: string;
  actual: number | null;
  forecast: number | null;
  flagged: boolean;
  [key: string]: unknown;
}

export async function getDemandVsForecast(days = 7): Promise<DemandPoint[]> {
  const rows = await sql<
    { time: Date; actual: number; forecast: number | null; forest_flagged: boolean | null }[]
  >`
    SELECT r.period_start AS time, r.value_mw AS actual,
      r.value_mw - a.residual AS forecast, a.forest_flagged
    FROM eia_readings r
    LEFT JOIN eia_anomalies a
      ON a.period_start = r.period_start AND a.reading_type = r.reading_type
    WHERE r.respondent = 'PJM' AND r.reading_type = 'D'
      AND r.period_start > now() - (${days} || ' days')::interval
    ORDER BY r.period_start
  `;
  return rows.map((r) => ({
    t: r.time.toISOString(),
    actual: r.actual,
    forecast: r.forecast,
    flagged: Boolean(r.forest_flagged),
  }));
}

export interface ResidualPoint {
  t: string;
  residual: number;
  flagged: boolean;
  [key: string]: unknown;
}

export async function getResiduals(days = 7): Promise<ResidualPoint[]> {
  const rows = await sql<{ time: Date; residual: number; forest_flagged: boolean | null }[]>`
    SELECT period_start AS time, residual, forest_flagged
    FROM eia_anomalies
    WHERE reading_type = 'D' AND period_start > now() - (${days} || ' days')::interval
    ORDER BY period_start
  `;
  return rows.map((r) => ({
    t: r.time.toISOString(),
    residual: r.residual,
    flagged: Boolean(r.forest_flagged),
  }));
}

export interface AnomalyLogRow {
  time: string;
  residualMw: number;
  forestScore: number | null;
  forestFlagged: boolean;
  flatlineFlagged: boolean;
  scoredAt: string;
}

export async function getAnomalyLog(limit = 100): Promise<AnomalyLogRow[]> {
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
    FROM eia_anomalies
    WHERE reading_type = 'D' AND (forest_flagged OR flatline_flagged)
    ORDER BY period_start DESC LIMIT ${limit}
  `;
  return rows.map((r) => ({
    time: r.time.toISOString(),
    residualMw: r.residual,
    forestScore: r.forest_score,
    forestFlagged: r.forest_flagged,
    flatlineFlagged: r.flatline_flagged,
    scoredAt: r.scored_at.toISOString(),
  }));
}

export interface GenInterchangePoint {
  t: string;
  netGenerationMw: number | null;
  totalInterchangeMw: number | null;
  [key: string]: unknown;
}

export async function getNetGenAndInterchange(days = 7): Promise<GenInterchangePoint[]> {
  const rows = await sql<
    { time: Date; net_generation: number | null; total_interchange: number | null }[]
  >`
    SELECT coalesce(ng.period_start, ti.period_start) AS time,
      ng.value_mw AS net_generation, ti.value_mw AS total_interchange
    FROM
      (SELECT period_start, value_mw FROM eia_readings
       WHERE respondent = 'PJM' AND reading_type = 'NG'
         AND period_start > now() - (${days} || ' days')::interval) ng
    FULL OUTER JOIN
      (SELECT period_start, value_mw FROM eia_readings
       WHERE respondent = 'PJM' AND reading_type = 'TI'
         AND period_start > now() - (${days} || ' days')::interval) ti
      ON ng.period_start = ti.period_start
    ORDER BY time
  `;
  return rows.map((r) => ({
    t: r.time.toISOString(),
    netGenerationMw: r.net_generation,
    totalInterchangeMw: r.total_interchange,
  }));
}
