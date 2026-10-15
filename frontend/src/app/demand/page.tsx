import {
  getAnomalyLog,
  getDemandVsForecast,
  getEiaSummary,
  getNetGenAndInterchange,
  getResiduals,
} from "@/lib/queries/eia";
import { ChartCard, StatsGrid, StatTile } from "@/components/ChartCard";
import { LineChart, ChartLegend } from "@/components/LineChart";


function fmtMw(v: number) {
  return Math.round(v).toLocaleString("en-US") + " MW";
}

function tooltipTime(raw: unknown) {
  return typeof raw === "string" ? raw.slice(5, 16).replace("T", " ") : String(raw);
}

export default async function DemandPage() {
  const [summary, demand, residuals, log, genInterchange] = await Promise.all([
    getEiaSummary(),
    getDemandVsForecast(7),
    getResiduals(7),
    getAnomalyLog(100),
    getNetGenAndInterchange(7),
  ]);

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-12">
      <div className="mb-1 text-[0.78rem] font-bold uppercase tracking-wide" style={{ color: "var(--ink-muted)" }}>
        Public, live
      </div>
      <h1 className="mb-6 text-3xl font-bold">PJM-wide demand</h1>
      <p className="mb-8 max-w-[680px]" style={{ color: "var(--ink-2)" }}>
        EIA-930 sourced: federal, public, unrestricted. This is the anomaly-detection pipeline&apos;s
        live output, not a snapshot -- an isolation forest scores the residual between actual
        demand and a seasonal-naive forecast, fit on data through mid-2025 and evaluated on a
        later window it never trained on.
      </p>

      <StatsGrid>
        <StatTile label="Current PJM demand" value={summary.currentMw ? fmtMw(summary.currentMw) : "--"} sub="most recent EIA-930 reading" />
        <StatTile label="24h peak demand" value={summary.peak24hMw ? fmtMw(summary.peak24hMw) : "--"} sub="rolling window" />
        <StatTile
          label="Data freshness"
          value={summary.freshnessSeconds != null ? `${Math.round(summary.freshnessSeconds / 60)}m` : "--"}
          sub="since last reading"
        />
        <StatTile label="Anomalies flagged" value={summary.anomalies7d} sub="last 7 days" />
      </StatsGrid>

      <div className="mt-6 grid gap-5 md:grid-cols-2">
        <ChartCard title="Demand vs. forecast" meta="EIA-930, hourly, 7 days">
          <LineChart
            data={demand}
            xKey="t"
            series={[
              { key: "actual", color: "var(--blue)", label: "Actual (MW)" },
              { key: "forecast", color: "var(--aqua)", label: "Forecast (MW)" },
            ]}
            flagKey="flagged"
            tooltipXLabel={tooltipTime}
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
            tooltipXLabel={tooltipTime}
          />
        </ChartCard>
      </div>

      <ChartCard title="Net generation and total interchange" meta="EIA-930, hourly, 7 days" footnote={undefined}>
        <LineChart
          data={genInterchange}
          xKey="t"
          series={[
            { key: "netGenerationMw", color: "var(--blue)", label: "Net generation" },
            { key: "totalInterchangeMw", color: "var(--orange)", label: "Total interchange" },
          ]}
          tooltipXLabel={tooltipTime}
        />
        <ChartLegend
          series={[
            { key: "netGenerationMw", color: "var(--blue)", label: "Net generation (MW)" },
            { key: "totalInterchangeMw", color: "var(--orange)", label: "Total interchange (MW)" },
          ]}
        />
      </ChartCard>

      <h2 className="mt-10 mb-3 text-xl font-bold">Flagged anomaly log</h2>
      <div className="overflow-x-auto rounded-[10px] border" style={{ borderColor: "var(--border)" }}>
        <table className="w-full min-w-[480px] border-collapse text-[0.88rem]">
          <thead>
            <tr>
              {["Time", "Residual (MW)", "Forest score", "Detector"].map((h) => (
                <th
                  key={h}
                  className="border-b px-3.5 py-2.5 text-left text-[0.72rem] font-semibold uppercase tracking-wide"
                  style={{ borderColor: "var(--border)", color: "var(--ink-muted)", background: "var(--surface-1)" }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {log.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3.5 py-4 text-center" style={{ color: "var(--ink-muted)" }}>
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
    </main>
  );
}
