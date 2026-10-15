import {
  getAnomalyLog,
  getDemandVsForecast,
  getEiaSummary,
  getNetGenAndInterchange,
  getResiduals,
} from "@/lib/queries/eia";
import { ChartCard, StatsGrid, StatTile } from "@/components/ChartCard";
import { LineChart, ChartLegend } from "@/components/LineChart";
import Link from "next/link";
import { numbering } from "@/lib/sources";
import { Cite, ReferenceList } from "@/components/Sources";
import { SNAPSHOT_LABEL, STATIC_DEMO } from "@/lib/staticDemo";


const REF_IDS = ["eia-gridmonitor"];

function median(values: number[]) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function fmtWhen(iso: string) {
  // "2026-10-12T23:00:00.000Z" -> "Oct 12, 23:00 UTC"
  const d = new Date(iso);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return `${month} ${d.getUTCDate()}, ${String(d.getUTCHours()).padStart(2, "0")}:00 UTC`;
}

function fmtMw(v: number) {
  return Math.round(v).toLocaleString("en-US") + " MW";
}

export default async function DemandPage() {
  const [summary, demand, residuals, log, genInterchange] = await Promise.all([
    getEiaSummary(),
    getDemandVsForecast(7),
    getResiduals(7),
    getAnomalyLog(100),
    getNetGenAndInterchange(7),
  ]);

  const n = numbering(REF_IDS);

  // Everything in "What this means" is computed from the same rows the charts draw.
  const actuals = demand.map((d) => d.actual).filter((v): v is number => typeof v === "number");
  const peak7 = actuals.length ? Math.max(...actuals) : null;
  const latestScored = [...demand].reverse().find((d) => typeof d.actual === "number" && typeof d.forecast === "number");
  const gap = latestScored ? (latestScored.actual as number) - (latestScored.forecast as number) : null;
  const typicalMiss = median(residuals.map((r) => Math.abs(r.residual)));
  const pctOfPeak =
    summary.currentMw != null && peak7 ? Math.round((summary.currentMw / peak7) * 100) : null;

  // A snapshot cannot show "minutes since the last reading": that figure is computed at build
  // time and would be wrong the moment it is published. Show the reading's own timestamp.
  const lastReading = demand.length ? demand[demand.length - 1].t : null;
  const window7 = STATIC_DEMO ? "the 7 days before the snapshot" : "the last 7 days";

  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-12">
      <h1 className="mb-4 text-3xl font-bold">PJM-wide demand</h1>
      <p className="mb-8 max-w-[680px]" style={{ color: "var(--ink-2)" }}>
        EIA-930 sourced: federal, public, unrestricted.
        <Cite id="eia-gridmonitor" nums={n} />{" "}
        {STATIC_DEMO
          ? `This is a snapshot of the anomaly-detection pipeline's output, taken ${SNAPSHOT_LABEL}.`
          : "This is the anomaly-detection pipeline's live output, not a snapshot."}{" "}
        An isolation forest scores the residual between actual
        demand and a seasonal-naive forecast, fit on data through mid-2025 and evaluated on a
        later window it never trained on.
      </p>

      <StatsGrid>
        <StatTile label="Current PJM demand" value={summary.currentMw ? fmtMw(summary.currentMw) : "--"} sub="most recent EIA-930 reading" />
        <StatTile
          label="24h peak demand"
          value={summary.peak24hMw ? fmtMw(summary.peak24hMw) : "--"}
          sub={STATIC_DEMO ? "24 hours before the snapshot" : "rolling window"}
        />
        {STATIC_DEMO ? (
          <StatTile
            label="Newest reading"
            value={lastReading ? fmtWhen(lastReading) : "--"}
            sub="in this snapshot"
          />
        ) : (
          <StatTile
            label="Data freshness"
            value={summary.freshnessSeconds != null ? `${Math.round(summary.freshnessSeconds / 60)}m` : "--"}
            sub="since last reading"
          />
        )}
        <StatTile
          label="Anomalies flagged"
          value={summary.anomalies7d}
          sub={STATIC_DEMO ? "7 days before the snapshot" : "last 7 days"}
        />
      </StatsGrid>

      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <ChartCard title="Demand vs. forecast" meta="EIA-930, hourly, 7 days">
          <LineChart
            data={demand}
            xKey="t"
            series={[
              { key: "actual", color: "var(--blue)", label: "Actual (MW)" },
              { key: "forecast", color: "var(--aqua)", label: "Forecast (MW)" },
            ]}
            flagKey="flagged"
          />
          <ChartLegend
            series={[
              { key: "actual", color: "var(--blue)", label: "Actual demand (MW)" },
              { key: "forecast", color: "var(--aqua)", label: "Forecast (MW)" },
            ]}
          />
        </ChartCard>

        <ChartCard title="Forecast residuals" meta="actual minus forecast, 7 days">
          <LineChart
            data={residuals}
            xKey="t"
            series={[{ key: "residual", color: "var(--orange)", label: "Residual (MW)" }]}
            flagKey="flagged"
          />
        </ChartCard>
      </div>

      <div className="mt-5">
      <ChartCard title="Net generation and total interchange" meta="EIA-930, hourly, 7 days">
        <LineChart
          data={genInterchange}
          xKey="t"
          series={[
            { key: "netGenerationMw", color: "var(--blue)", label: "Net generation" },
            { key: "totalInterchangeMw", color: "var(--orange)", label: "Total interchange" },
          ]}
        />
        <ChartLegend
          series={[
            { key: "netGenerationMw", color: "var(--blue)", label: "Net generation (MW)" },
            { key: "totalInterchangeMw", color: "var(--orange)", label: "Total interchange (MW)" },
          ]}
        />
      </ChartCard>
      </div>

      <section className="mt-12 max-w-[680px]" aria-labelledby="what-this-means">
        <h2 id="what-this-means" className="mb-3 text-xl font-bold">
          What this means
        </h2>
        <p>
          {summary.currentMw != null && peak7 != null && pctOfPeak != null ? (
            <>
              PJM demand was {fmtMw(summary.currentMw)} {STATIC_DEMO ? "at the time of this snapshot" : "right now"}, {pctOfPeak}% of the{" "}
              {fmtMw(peak7)} peak of the seven days before it.
            </>
          ) : (
            <>Current demand is unavailable.</>
          )}{" "}
          {latestScored && gap != null && typicalMiss != null ? (
            <>
              At the latest scored hour ({fmtWhen(latestScored.t)}), actual demand was {fmtMw(Math.abs(gap))} {gap >= 0 ? "above" : "below"} the forecast,
              against a typical miss of about {fmtMw(typicalMiss)} over the week.
            </>
          ) : null}
        </p>
        <p>
          <b>How to read the charts.</b> The blue line is what EIA reports. The green line is what
          a simple seasonal forecast expected for the same hour: the same hour a week earlier. The
          residuals chart is the gap between the two, and that gap is the series the detector
          actually scores.
        </p>
        <p>
          <b>What a red dot means.</b> A flagged hour is one where that gap looked unusual
          compared with history, given the time of day and recent behavior. It is not a confirmed
          outage or event, and there are no ground-truth labels to check it against.{" "}
          {summary.anomalies7d === 0
            ? `Nothing was flagged in ${window7}.`
            : `${summary.anomalies7d} ${summary.anomalies7d === 1 ? "hour was" : "hours were"} flagged in ${window7}${log[0] ? `, the most recent at ${fmtWhen(log[0].time)}` : ""}.`}
        </p>
        <p>
          <b>Why a hot afternoon is not an anomaly.</b> The detector scores the gap, not the
          demand level. A July peak is high but expected, so it is not flagged. Something the
          forecast did not see coming is.
        </p>
        <p>
          <b>What it cannot tell you.</b> These are PJM-wide totals, so nothing here can be
          narrowed to Pennsylvania, a single utility, or a single data center. If data centers are
          adding load, it would mostly show up as a gradual rise in the baseline, which a forecast
          that looks back one week absorbs, rather than as individual flagged hours. Weather,
          electrification and industry move demand too, so no cause is attributed here. For the
          claims being checked, see the <Link href="/">case study</Link>; for where reported
          projects sit, see the <Link href="/map">PA map</Link>.
        </p>
        <p>
          <b>How fresh it is.</b> EIA publishes hours after the fact and restates figures later,
          so {STATIC_DEMO ? "the newest reading above lags the snapshot time" : "the freshness tile above is the age of the newest reading, not of the grid"}. Recent
          values can change.
          <Cite id="eia-gridmonitor" nums={n} />
        </p>
      </section>

      <h2 className="mt-12 mb-3 text-xl font-bold">Flagged anomaly log</h2>
      <div className="overflow-x-auto rounded-[10px] border" style={{ borderColor: "var(--border)" }}>
        <table className={`w-full border-collapse text-[0.9rem] ${log.length > 0 ? "min-w-[480px]" : ""}`}>
          <caption className="sr-only">Flagged anomalies, most recent first</caption>
          <thead>
            <tr>
              {["Time", "Residual (MW)", "Forest score", "Detector"].map((h) => (
                <th
                  key={h}
                  scope="col"
                  className="border-b px-3.5 py-2.5 text-left text-[0.75rem] font-semibold uppercase tracking-wide"
                  style={{ borderColor: "var(--border)", color: "var(--ink-2)", background: "var(--surface-1)" }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {log.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3.5 py-6 text-center" style={{ color: "var(--ink-2)" }}>
                  No anomalies flagged yet.
                </td>
              </tr>
            )}
            {log.map((row) => (
              <tr key={row.time}>
                <td className="border-b px-3.5 py-2.5 tabular-nums" style={{ borderColor: "var(--border)" }}>
                  {row.time.slice(0, 16).replace("T", " ")}
                </td>
                <td className="border-b px-3.5 py-2.5 tabular-nums" style={{ borderColor: "var(--border)" }}>
                  {Math.round(row.residualMw).toLocaleString("en-US")}
                </td>
                <td className="border-b px-3.5 py-2.5 tabular-nums" style={{ borderColor: "var(--border)" }}>
                  {row.forestScore?.toFixed(3) ?? "--"}
                </td>
                <td className="border-b px-3.5 py-2.5" style={{ borderColor: "var(--border)" }}>
                  {row.forestFlagged ? "Forest" : row.flatlineFlagged ? "Flatline" : "--"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-12 max-w-[680px]">
        <ReferenceList ids={REF_IDS} nums={n} />
      </div>
    </main>
  );
}
