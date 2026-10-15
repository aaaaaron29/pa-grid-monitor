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
  const abs = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (v < 0 ? "-$" : "$") + abs;
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
    <main className="mx-auto w-full max-w-[1100px] px-4 py-12">
      <div className="mb-1 text-[0.8rem] font-semibold" style={{ color: "var(--ink-2)" }}>
        Private: PJM Data Miner 2 sourced
      </div>
      <h1 className="mb-5 text-3xl font-bold">PJM zone LMP</h1>

      <nav aria-label="Zone" className="mb-6 flex flex-wrap gap-2">
        {ZONES.map((z) => (
          <Link
            key={z}
            href={`/private/zones?zone=${z}`}
            aria-current={z === zone ? "page" : undefined}
            className="rounded-full px-3.5 py-1.5 text-sm font-semibold no-underline hover:brightness-110"
            style={{
              background: z === zone ? "var(--orange)" : "var(--surface-1)",
              color: z === zone ? "#0b0b0b" : "var(--ink-2)",
              border: "1px solid var(--border)",
            }}
          >
            {z}
          </Link>
        ))}
      </nav>

      <StatsGrid>
        <StatTile label={`Current LMP (${zone})`} value={summary.currentPrice != null ? fmtPrice(summary.currentPrice) : "--"} />
        <StatTile label="24h peak LMP" value={summary.peak24hPrice != null ? fmtPrice(summary.peak24hPrice) : "--"} />
        <StatTile
          label="Data freshness"
          value={summary.freshnessSeconds != null ? `${Math.round(summary.freshnessSeconds / 60)}m` : "--"}
        />
        <StatTile label="Anomalies (7d)" value={summary.anomalies7d} />
      </StatsGrid>

      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <ChartCard title={`LMP vs. forecast (${zone})`} meta="hourly, 7 days">
          <LineChart
            data={lmp}
            series={[
              { key: "actual", color: "var(--orange)", label: "Actual" },
              { key: "forecast", color: "var(--aqua)", label: "Forecast" },
            ]}
            flagKey="flagged"
            yFormat="usd"
          />
        </ChartCard>
        <ChartCard title={`Forecast residuals (${zone})`} meta="hourly, 7 days">
          <LineChart
            data={residuals}
            series={[{ key: "residual", color: "var(--blue)", label: "Residual" }]}
            flagKey="flagged"
            yFormat="usd"
          />
        </ChartCard>
      </div>

      <h2 className="mt-12 mb-3 text-xl font-bold">All five zones, anomalies (7d)</h2>
      <div className="mb-12 grid grid-cols-2 gap-px sm:grid-cols-5 [&>*:last-child]:col-span-2 sm:[&>*:last-child]:col-span-1 overflow-hidden rounded-[10px] border" style={{ background: "var(--border)", borderColor: "var(--border)" }}>
        {ZONES.map((z) => {
          const count = allCounts.find((c) => c.zone === z)?.count ?? 0;
          return (
            <div key={z} className="p-4" style={{ background: "var(--surface-1)" }}>
              <div className="text-sm font-semibold" style={{ color: "var(--ink-2)" }}>{z}</div>
              <div className="text-xl font-bold tabular-nums">{count}</div>
            </div>
          );
        })}
      </div>

      <h2 className="mb-3 text-xl font-bold">Anomaly log ({zone})</h2>
      <div className="overflow-x-auto rounded-[10px] border" style={{ borderColor: "var(--border)" }}>
        <table className={`w-full border-collapse text-[0.9rem] ${log.length > 0 ? "min-w-[480px]" : ""}`}>
          <caption className="sr-only">Flagged anomalies for {zone}, most recent first</caption>
          <thead>
            <tr>
              {["Time", "Residual ($/MWh)", "Forest score", "Detector"].map((h) => (
                <th key={h} scope="col" className="border-b px-3.5 py-2.5 text-left text-[0.75rem] font-semibold uppercase tracking-wide" style={{ borderColor: "var(--border)", color: "var(--ink-2)", background: "var(--surface-1)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {log.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3.5 py-6 text-center" style={{ color: "var(--ink-2)" }}>
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

      <p className="mt-12">
        <Link href="/private/accountability">The PPL promises-vs-measured load comparison &rarr;</Link>
      </p>
      <p className="mt-3">
        <Link href="/private/map">The PA map with zone overlay &rarr;</Link>
      </p>
    </main>
  );
}
