import Link from "next/link";
import {
  ZONES,
  type Zone,
  getAllZoneAnomalyCounts,
  getLmpVsForecast,
  getZoneAnomalyLog,
  getZoneResiduals,
  getZoneSummary,
} from "@/lib/queries/pjm";
import { ChartCard, StatsGrid, StatTile } from "@/components/ChartCard";
import { LineChart } from "@/components/LineChart";


function fmtPrice(v: number) {
  return "$" + v.toFixed(2);
}

function tooltipTime(raw: unknown) {
  return typeof raw === "string" ? raw.slice(5, 16).replace("T", " ") : String(raw);
}

function isZone(v: string | undefined): v is Zone {
  return Boolean(v) && (ZONES as readonly string[]).includes(v!);
}

export default async function ZonesPage({ searchParams }: PageProps<"/private/zones">) {
  const params = await searchParams;
  const zone: Zone = isZone(params.zone as string | undefined) ? (params.zone as Zone) : "PECO";

  const [summary, lmp, residuals, log, allCounts] = await Promise.all([
    getZoneSummary(zone),
    getLmpVsForecast(zone, 7),
    getZoneResiduals(zone, 7),
    getZoneAnomalyLog(zone, 100),
    getAllZoneAnomalyCounts(),
  ]);

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-12">
      <div className="mb-1 text-[0.78rem] font-bold uppercase tracking-wide" style={{ color: "var(--orange)" }}>
        Private -- PJM Data Miner 2 sourced
      </div>
      <h1 className="mb-6 text-3xl font-bold">PJM zone LMP</h1>

      <div className="mb-6 flex gap-2">
        {ZONES.map((z) => (
          <Link
            key={z}
            href={`/private/zones?zone=${z}`}
            className="rounded-full px-3 py-1 text-sm font-semibold"
            style={{
              background: z === zone ? "var(--orange)" : "var(--surface-1)",
              color: z === zone ? "white" : "var(--ink-2)",
              border: "1px solid var(--border)",
            }}
          >
            {z}
          </Link>
        ))}
      </div>

      <StatsGrid>
        <StatTile label={`Current LMP (${zone})`} value={summary.currentPrice != null ? fmtPrice(summary.currentPrice) : "--"} />
        <StatTile label="24h peak LMP" value={summary.peak24hPrice != null ? fmtPrice(summary.peak24hPrice) : "--"} />
        <StatTile
          label="Data freshness"
          value={summary.freshnessSeconds != null ? `${Math.round(summary.freshnessSeconds / 60)}m` : "--"}
        />
        <StatTile label="Anomalies (7d)" value={summary.anomalies7d} />
      </StatsGrid>

      <div className="mt-6 grid gap-5 md:grid-cols-2">
        <ChartCard title={`LMP vs. forecast (${zone})`} meta="hourly, 7 days">
          <LineChart
            data={lmp}
            series={[
              { key: "actual", color: "var(--orange)", label: "Actual" },
              { key: "forecast", color: "var(--aqua)", label: "Forecast" },
            ]}
            flagKey="flagged"
            yFormat={fmtPrice}
            tooltipXLabel={tooltipTime}
          />
        </ChartCard>
        <ChartCard title={`Forecast residuals (${zone})`} meta="hourly, 7 days">
          <LineChart
            data={residuals}
            series={[{ key: "residual", color: "var(--blue)", label: "Residual" }]}
            flagKey="flagged"
            yFormat={fmtPrice}
            tooltipXLabel={tooltipTime}
          />
        </ChartCard>
      </div>

      <h2 className="mt-10 mb-3 text-xl font-bold">All five zones, anomalies (7d)</h2>
      <div className="mb-10 grid grid-cols-5 gap-px overflow-hidden rounded-[10px] border" style={{ background: "var(--border)", borderColor: "var(--border)" }}>
        {ZONES.map((z) => {
          const count = allCounts.find((c) => c.zone === z)?.count ?? 0;
          return (
            <div key={z} className="p-4" style={{ background: "var(--surface-1)" }}>
              <div className="text-sm font-bold">{z}</div>
              <div className="text-xl font-bold tabular-nums">{count}</div>
            </div>
          );
        })}
      </div>

      <h2 className="mb-3 text-xl font-bold">Anomaly log ({zone})</h2>
      <div className="overflow-x-auto rounded-[10px] border" style={{ borderColor: "var(--border)" }}>
        <table className="w-full min-w-[480px] border-collapse text-[0.88rem]">
          <thead>
            <tr>
              {["Time", "Residual ($/MWh)", "Forest score", "Detector"].map((h) => (
                <th key={h} className="border-b px-3.5 py-2.5 text-left text-[0.72rem] font-semibold uppercase" style={{ borderColor: "var(--border)", color: "var(--ink-muted)", background: "var(--surface-1)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {log.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3.5 py-4 text-center" style={{ color: "var(--ink-muted)" }}>
                  No anomalies flagged yet for {zone}.
                </td>
              </tr>
            )}
            {log.map((row) => (
              <tr key={row.time}>
                <td className="border-b px-3.5 py-2.5 tabular-nums" style={{ borderColor: "var(--border)" }}>{row.time.slice(0, 16).replace("T", " ")}</td>
                <td className="border-b px-3.5 py-2.5 tabular-nums" style={{ borderColor: "var(--border)" }}>{row.residualPrice.toFixed(2)}</td>
                <td className="border-b px-3.5 py-2.5 tabular-nums" style={{ borderColor: "var(--border)" }}>{row.forestScore?.toFixed(3) ?? "--"}</td>
                <td className="border-b px-3.5 py-2.5" style={{ borderColor: "var(--border)" }}>{row.forestFlagged ? "Forest" : row.flatlineFlagged ? "Flatline" : "--"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-10">
        <Link href="/private/accountability">The PPL promises-vs-measured load comparison &rarr;</Link>
      </p>
    </main>
  );
}
