import Link from "next/link";
import { getEiaReadingCount } from "@/lib/queries/eia";


// Public route. Only EIA-930 figures (federal, unrestricted) ever appear here -- PJM
// Data Miner 2 sourced data (LMP, load, and the PPL promises-vs-measured comparison that
// depends on it) lives behind /private/*. See ARCHITECTURE.md Section 9 item 7 for why.
// This content is a deliberate re-audit of docs/index.html's prose, not a straight port:
// two lines there (a "+3%" load-growth stat and a "hasn't moved much yet" conclusion)
// were themselves derived from Data Miner 2 data and are excluded here.

export default async function HomePage() {
  const eiaReadingCount = await getEiaReadingCount();

  return (
    <main className="mx-auto max-w-[680px] px-4 py-14">
      <div className="mb-1 text-[0.78rem] font-bold uppercase tracking-wide" style={{ color: "var(--ink-muted)" }}>
        Grid Watch
      </div>
      <h1 className="mb-3 text-[2.2rem] leading-tight font-bold text-balance">
        Are Pennsylvania&apos;s utilities delivering on their data center promises?
      </h1>
      <p className="mb-5 text-[1.05rem]">
        PPL Electric has told regulators and investors, repeatedly and on the record, how much
        new power demand is coming. PJM&apos;s own grid data is the only honest way to check if
        that&apos;s actually happening.
      </p>
      <div className="mb-10 flex flex-wrap gap-5 text-sm" style={{ color: "var(--ink-2)" }}>
        <div>
          <b className="text-[1.3rem] tabular-nums" style={{ color: "var(--ink-1)" }}>
            31.8 GW
          </b>{" "}
          PPL&apos;s own pipeline figure, Q2 2026
        </div>
        <div>
          <b className="text-[1.3rem] tabular-nums" style={{ color: "var(--ink-1)" }}>
            {eiaReadingCount.toLocaleString("en-US")}
          </b>{" "}
          real EIA-930 readings behind this page
        </div>
      </div>

      <section className="mb-10">
        <h2 className="mb-3 text-xl font-bold">Why this exists</h2>
        <p>
          This started as a real-time anomaly detector on the PJM grid: an isolation forest
          scoring forecast residuals across five Pennsylvania utility zones, built and verified
          end to end (ingestion, Kafka streaming, Kubernetes, CI). That pipeline is live --
          see the <Link href="/demand">PJM demand</Link> page for real output from it, not mockups.
        </p>
        <p>
          What it&apos;s turning into is more specific. PJM&apos;s wholesale power market is
          short on supply, and PJM&apos;s own capacity auction is pointing at one cause: AI data
          center demand. Pennsylvania utilities have made public, dated, numbered claims about
          how much of that demand is coming to their territory. Those claims are checkable
          against real metered data. This page is the first pass at doing that.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="mb-3 text-xl font-bold">PPL&apos;s pipeline, quarter by quarter</h2>
        <p>
          PPL Electric covers roughly 29 counties across central and eastern Pennsylvania,
          stretching from Lancaster through the Lehigh Valley to Scranton/Wilkes-Barre.
          It&apos;s the one PA utility Pennsylvania&apos;s own Public Utility Commission names
          as facing significant data-center-driven demand growth; the other four zones this
          project tracks are explicitly not.
        </p>
        <div className="mt-4 flex flex-col">
          {[
            {
              date: "Q1 2024",
              claim: "~3 GW in signed data center agreements",
              source: (
                <>
                  Earnings coverage, cited in{" "}
                  <a href="https://www.datacenterdynamics.com/en/news/us-utility-ppl-sees-data-center-pipeline-swell-by-23-percent-to-252gw/" target="_blank" rel="noopener">
                    Data Center Dynamics
                  </a>
                </>
              ),
            },
            {
              date: "Aug 2025",
              claim: "Data center load projected: 800MW in 2026 → 14.4GW by 2034",
              source: (
                <>
                  <a href="https://penncapital-star.com/uncategorized/data-centers-drive-higher-forecasts-for-electric-demand-in-pa-sparking-climate-worries/" target="_blank" rel="noopener">
                    Pennsylvania Capital-Star
                  </a>
                  . The 800MW-in-2026 figure is checkable against real PJM load data (see the
                  note below on where that comparison lives).
                </>
              ),
            },
            {
              date: "Q4 2025",
              claim: "25.2 GW in signed agreements",
              source: (
                <a href="https://www.datacenterdynamics.com/en/news/us-utility-ppl-sees-data-center-pipeline-swell-by-23-percent-to-252gw/" target="_blank" rel="noopener">
                  Data Center Dynamics
                </a>
              ),
            },
            {
              date: "Jan 2026",
              claim: "PJM's own forecast for PPL's territory summer peak: 7,300 MW → 12,000 MW",
              source: "PJM's 2026 Load Forecast Report. This one is PJM's independently published number, not PPL's own PR.",
            },
            {
              date: "Q2 2026",
              claim: "31.8 GW pipeline · 11 GW signed · 6.5 GW under construction",
              source: (
                <>
                  <a href="https://www.investing.com/news/company-news/ppl-q2-2026-slides-data-center-growth-drives-23b-capex-plan-93CH-4847201" target="_blank" rel="noopener">
                    PPL Q2 2026 investor materials
                  </a>
                  . Joint venture with Blackstone (Invitium Energy) has secured sites for
                  8&ndash;14 GW of new generation.
                </>
              ),
            },
          ].map((item) => (
            <div key={item.date} className="grid grid-cols-[110px_1fr] gap-5 border-t py-4 first:border-t-0" style={{ borderColor: "var(--border)" }}>
              <div className="pt-0.5 text-[0.82rem] font-bold" style={{ color: "var(--ink-muted)" }}>
                {item.date}
              </div>
              <div>
                <div className="mb-1 font-semibold">{item.claim}</div>
                <div className="text-[0.85rem]">{item.source}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-10">
        <h2 className="mb-3 text-xl font-bold">Why these numbers might not mean what they say</h2>
        <div className="rounded-lg border-l-[3px] border p-5" style={{ borderColor: "var(--border)", borderLeftColor: "var(--orange)", background: "var(--surface-1)" }}>
          <h3 className="mb-1 font-bold" style={{ color: "var(--orange)" }}>
            The duplicate-request problem
          </h3>
          <p className="mb-0">
            A July 2025{" "}
            <a href="https://eta-publications.lbl.gov/sites/default/files/2025-10/lbnl_lllreview_sept_update_2025_1.pdf" target="_blank" rel="noopener">
              London Economics analysis
            </a>{" "}
            argues pipeline figures like these are structurally inflated: developers routinely
            file interconnection requests at multiple candidate sites simultaneously while
            deciding where to actually build, so the same project can show up in several
            utilities&apos; &quot;pipeline&quot; totals at once. The same report flags equipment
            and chip supply bottlenecks as a separate reason real load growth could come in
            well below what&apos;s announced.
          </p>
        </div>
        <p className="mt-5">
          This is exactly why an accountability check is worth building, not a reason to skip
          it. There are two competing public stories: explosive, utility-reported growth, and
          analyst skepticism that it&apos;s overstated. Real metered demand is the only neutral
          referee between them.
        </p>
      </section>

      <section className="mb-10 rounded-lg border p-5" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
        <h2 className="mb-2 text-lg font-bold">Where the real measured comparison lives</h2>
        <p className="mb-0">
          The actual PPL load-vs-promises comparison is built and running on real data, but it
          isn&apos;t shown here. PJM&apos;s Data Miner 2 API terms prohibit non-member
          redistribution of data derived from it, and the comparison depends on zone-level LMP
          and load readings from that feed. It&apos;s being tracked internally, not abandoned --
          making it public depends on resolving a PJM data redistribution license, a separate
          piece of work from the pipeline itself.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="mb-3 text-xl font-bold">What this does and doesn&apos;t prove</h2>
        <p>
          <b style={{ color: "var(--ink-1)" }}>How the detection works:</b> an isolation forest
          scores the residual between actual demand and a seasonal-naive forecast (same hour,
          same day of week, prior cycle) plus rolling context, fit only on data through
          mid-2025 and evaluated on a later window it never trained on. There are no real
          anomaly labels for this data; detector quality is measured by injecting synthetic
          anomalies into held-out data and checking recall at a fixed false-positive budget.
          That&apos;s a check on the method, not a guarantee about any specific real event.
        </p>
        <p>
          <b style={{ color: "var(--ink-1)" }}>Why this is a PPL story, not a five-zone story:</b>{" "}
          Pennsylvania&apos;s PUC explicitly says the other four zones tracked here aren&apos;t
          expecting significant data-center impact. Treating this as a statewide comparison
          would overstate what the data supports.
        </p>
        <p>
          <b style={{ color: "var(--ink-1)" }}>Correlation, never causation:</b> PA demand can
          move for reasons that have nothing to do with data centers: weather, broader
          electrification, EV adoption, ordinary industrial growth. Nothing here is designed or
          intended to prove a single cause.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="mb-3 text-xl font-bold">Every claim above, linked</h2>
        <div className="flex flex-col gap-0.5 text-[0.88rem]">
          {[
            ["Primary", <>PA PUC, <a href="https://www.puc.pa.gov/media/3586/final-draft-2025-epo-2024-2029-8-2025.pdf" target="_blank" rel="noopener">Electric Power Outlook 2024&ndash;2029</a>: the regulatory finding that PPL alone faces significant data-center demand growth among PA&apos;s utilities.</>],
            ["Primary", <>PJM, <a href="https://www.pjm.com/-/media/DotCom/library/reports-notices/load-forecast/2026-load-report.pdf" target="_blank" rel="noopener">2026 Load Forecast Report</a>: PJM&apos;s own independent peak-demand forecast revisions.</>],
            ["Trade press", <><a href="https://www.datacenterdynamics.com/en/news/us-utility-ppl-sees-data-center-pipeline-swell-by-23-percent-to-252gw/" target="_blank" rel="noopener">Data Center Dynamics</a>, <a href="https://www.utilitydive.com/news/ppl-data-center-pipeline-pjm-blackstone-earnings/819804/" target="_blank" rel="noopener">Utility Dive</a> on PPL&apos;s pipeline growth.</>],
            ["Local news", <><a href="https://whyy.org/articles/peco-data-centers-agreement/" target="_blank" rel="noopener">WHYY</a> on PECO&apos;s Transmission Security Agreements; <a href="https://penncapital-star.com/uncategorized/data-centers-drive-higher-forecasts-for-electric-demand-in-pa-sparking-climate-worries/" target="_blank" rel="noopener">Pennsylvania Capital-Star</a> on the 2026&ndash;2034 load trajectory.</>],
            ["Market data", <><a href="https://www.utilitydive.com/news/pjm-interconnection-capacity-auction-data-center/808264/" target="_blank" rel="noopener">Utility Dive</a>, <a href="https://ieefa.org/resources/projected-data-center-growth-spurs-pjm-capacity-prices-factor-10" target="_blank" rel="noopener">IEEFA</a> on the July 2026 capacity auction shortfall.</>],
            ["Skeptic", <><a href="https://eta-publications.lbl.gov/sites/default/files/2025-10/lbnl_lllreview_sept_update_2025_1.pdf" target="_blank" rel="noopener">Lawrence Berkeley National Lab, Large Load Literature Review</a>: the duplicate-interconnection-request and overestimation critique.</>],
          ].map(([tag, body], i) => (
            <div key={i} className="flex gap-2.5 border-t py-2.5 first:border-t-0" style={{ borderColor: "var(--border)" }}>
              <div className="w-[86px] flex-none pt-0.5 text-[0.68rem] font-bold uppercase" style={{ color: "var(--ink-muted)" }}>
                {tag as string}
              </div>
              <div>{body}</div>
            </div>
          ))}
        </div>
      </section>

      <footer className="pt-8 pb-12 text-[0.8rem]" style={{ color: "var(--ink-muted)" }}>
        Live pipeline. Numbers on this page and on <Link href="/demand">/demand</Link> refresh on
        every request, read straight from Postgres.
      </footer>
    </main>
  );
}
