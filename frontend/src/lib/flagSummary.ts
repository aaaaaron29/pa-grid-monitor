// Plain-language numbers about the flagged (red-dot) intervals in a chart's own data, so the
// explanation next to the chart describes what is on screen rather than a fixed claim.

export interface FlagPoint {
  t: string;
  flagged: boolean;
  actual?: number | null;
  residual?: number | null;
}

export interface FlagSummary {
  scored: number;
  flagged: number;
  events: number;
  /** Flagged intervals whose own price is beyond SPIKE_PRICE in either direction. */
  onSpike: number;
  /** Largest flagged forecast miss, in $/MWh, with the interval it happened in. */
  biggestMiss: { value: number; t: string } | null;
}

export const SPIKE_PRICE = 300;
const EVENT_GAP_MS = 60 * 60 * 1000;

export function summarizeFlags(points: FlagPoint[]): FlagSummary {
  let flagged = 0;
  let events = 0;
  let onSpike = 0;
  let lastFlag = -Infinity;
  let biggest: FlagSummary["biggestMiss"] = null;
  for (const p of points) {
    if (!p.flagged) continue;
    flagged += 1;
    const at = Date.parse(p.t);
    if (at - lastFlag > EVENT_GAP_MS) events += 1;
    lastFlag = at;
    if (typeof p.actual === "number" && Math.abs(p.actual) > SPIKE_PRICE) onSpike += 1;
    if (typeof p.residual === "number" && (!biggest || Math.abs(p.residual) > Math.abs(biggest.value))) {
      biggest = { value: p.residual, t: p.t };
    }
  }
  return { scored: points.length, flagged, events, onSpike, biggestMiss: biggest };
}
