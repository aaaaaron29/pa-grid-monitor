import { getPplLoadYearOverYear, getPplMonthlyLoad } from "@/lib/queries/pjm";
import { ChartCard, StatsGrid, StatTile } from "@/components/ChartCard";
import { LineChart, ChartLegend } from "@/components/LineChart";


const CLAIM_MONTHS = [
  { month: "2024-01", label: "1" },
  { month: "2025-08", label: "2" },
  { month: "2025-12", label: "3" },
  { month: "2026-01", label: "4" },
  { month: "2026-06", label: "5" },
];

function pct(from: number, to: number) {
  const change = ((to - from) / from) * 100;
  return `${change >= 0 ? "+" : ""}${change.toFixed(1)}%`;
}

export default async function AccountabilityPage() {
  const [monthly, yoy] = await Promise.all([getPplMonthlyLoad(), getPplLoadYearOverYear()]);

  const annotations = CLAIM_MONTHS.map((c) => {
    const index = monthly.findIndex((m) => m.month === c.month);
    return index >= 0 ? { index, label: c.label } : null;
  }).filter((a): a is { index: number; label: string } => a !== null);

  const first = yoy[0];
  const last = yoy[yoy.length - 1];

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-12">
      <div className="mb-1 text-[0.78rem] font-bold uppercase tracking-wide" style={{ color: "var(--orange)" }}>
        Private -- PJM Data Miner 2 sourced
      </div>
      <h1 className="mb-3 text-3xl font-bold">Promises vs. measured reality</h1>
      <p className="mb-8 max-w-[680px]" style={{ color: "var(--ink-2)" }}>
        PJM&apos;s <code>hrl_load_metered</code> feed, ingested back to December 2023 for all
        five PA zones. PPL&apos;s actual zone-wide load laid against the same claims timeline
        from the home page.
      </p>

      {first && last && (
        <StatsGrid cols={3}>
          <StatTile
            label={`PPL avg load, ${first.year}→${last.year}`}
            value={pct(first.avgMw, last.avgMw)}
            sub={`${Math.round(first.avgMw).toLocaleString()} → ${Math.round(last.avgMw).toLocaleString()} MW`}
          />
          <StatTile
            label={`PPL peak load, ${first.year}→${last.year}`}
            value={pct(first.peakMw, last.peakMw)}
            sub={`${Math.round(first.peakMw).toLocaleString()} → ${Math.round(last.peakMw).toLocaleString()} MW`}
          />
          <StatTile label="Signed pipeline, same window" value="~3 → 31.8 GW" sub="PPL's own reported figures" />
        </StatsGrid>
      )}

      <div className="mt-6">
        <ChartCard title="PPL zone load, monthly average & peak" meta="PJM hrl_load_metered, live">
          <LineChart
            data={monthly}
            xKey="month"
            series={[
              { key: "peakMw", color: "var(--aqua)", label: "Monthly peak (MW)" },
              { key: "avgMw", color: "var(--blue)", label: "Monthly average (MW)" },
            ]}
            annotations={annotations}
            xLabelEvery={6}
            xTickLabel={(raw) => String(raw)}
            tooltipXLabel={(raw) => String(raw)}
            height={260}
          />
          <ChartLegend
            series={[
              { key: "avgMw", color: "var(--blue)", label: "Monthly average (MW)" },
              { key: "peakMw", color: "var(--aqua)", label: "Monthly peak (MW)" },
            ]}
          />
          <p className="mt-2.5 text-[0.78rem]" style={{ color: "var(--ink-muted)" }}>
            Numbered markers: <b>1</b> Q1&apos;24 ~3GW signed &middot; <b>2</b> Aug&apos;25
            800MW-by-2026/14.4GW-by-2034 forecast &middot; <b>3</b> Q4&apos;25 25.2GW signed
            &middot; <b>4</b> Jan&apos;26 PJM peak forecast raised to 12,000MW &middot;{" "}
            <b>5</b> Q2&apos;26 31.8GW pipeline
          </p>
        </ChartCard>
      </div>

      <p className="mt-6 max-w-[680px]">
        The seasonal pattern (winter and summer peaks, spring/fall troughs) is the normal shape
        of electricity demand and has nothing to do with data centers. What matters is whether
        that pattern is climbing over time. At zone-wide scale it mostly isn&apos;t yet, while
        the claims themselves grew roughly tenfold over the same window.
      </p>

      <div className="mt-4 max-w-[680px] rounded-lg border-l-[3px] border p-5" style={{ borderColor: "var(--border)", borderLeftColor: "var(--orange)", background: "var(--surface-1)" }}>
        <h3 className="mb-1 font-bold" style={{ color: "var(--orange)" }}>
          Why this isn&apos;t &quot;PPL is lying&quot;
        </h3>
        <p className="mb-0">
          Signed and pipeline agreements are not the same thing as load already drawing power.
          Data center interconnection and construction routinely takes several years, and
          PPL&apos;s own numbers distinguish &quot;signed&quot; (11 GW) from &quot;under
          construction&quot; (6.5 GW) from total pipeline (31.8 GW) for exactly this reason. A
          zone-wide total also can&apos;t separate new data-center load from anything else
          happening in a 29-county territory. The honest read of this chart isn&apos;t
          &quot;the promises are false,&quot; it&apos;s &quot;the promised load hasn&apos;t
          landed yet, at the zone-wide level, as of this snapshot.&quot; That gap is exactly
          what this page should keep tracking, quarter over quarter, as more of that 31.8 GW
          either comes online or doesn&apos;t.
        </p>
      </div>

      <p className="mt-4 max-w-[680px] text-[0.86rem]" style={{ color: "var(--ink-muted)" }}>
        One honesty note on the data itself: PJM&apos;s feed never marks PPL&apos;s largest load
        component (PLCO, the bulk of the zone) as settlement-verified, unlike METED, PECO, and
        PENELEC. Duquesne&apos;s zone has the same gap. The numbers above are PJM&apos;s real
        metered readings, just ones PJM itself has not flagged as final.
      </p>
    </main>
  );
}
