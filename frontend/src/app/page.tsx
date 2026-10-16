import Link from "next/link";
import { getEiaReadingCount } from "@/lib/queries/eia";
import { numbering } from "@/lib/sources";
import { SNAPSHOT_LABEL, STATIC_DEMO } from "@/lib/staticDemo";
import { Cite, ReferenceList, SourceChip } from "@/components/Sources";
import { SectionRail } from "@/components/SectionRail";

const RAIL = [
  { id: "overview", label: "The question" },
  { id: "why-this-exists", label: "Why this exists" },
  { id: "pipeline", label: "PPL's pipeline, quarter by quarter" },
  { id: "caveats", label: "Why the numbers may mislead" },
  { id: "measured-comparison", label: "Where the measured comparison lives" },
  { id: "limits", label: "What this does and doesn't prove" },
  { id: "refs-heading", label: "Sources" },
];

// Public route. Only EIA-930 figures (federal, unrestricted) ever appear here -- PJM
// Data Miner 2 sourced data (LMP, load, and the PPL promises-vs-measured comparison that
// depends on it) lives behind /private/*. See ARCHITECTURE.md Section 9 item 7 for why.
// This content is a deliberate re-audit of docs/index.html's prose, not a straight port:
// two lines there (a "+3%" load-growth stat and a "hasn't moved much yet" conclusion)
// were themselves derived from Data Miner 2 data and are excluded here.

// Reference numbers follow order of first appearance on the page.
const REF_IDS = [
  "investing-ppl-q2",
  "utilitydive-capacity",
  "ieefa-capacity",
  "puc-epo",
  "dcd-ppl-pipeline",
  "capitalstar-load",
  "pjm-load-2026",
  "lei-report",
  "lbnl-llr",
  "whyy-peco",
  "utilitydive-ppl",
];

export default async function HomePage() {
  const eiaReadingCount = await getEiaReadingCount();
  const n = numbering(REF_IDS);

  const timeline = [
    {
      date: "Q1 2024",
      claim: "~3 GW in signed data center agreements",
      source: (
        <>
          Earnings coverage, cited in <SourceChip id="dcd-ppl-pipeline" />
        </>
      ),
    },
    {
      date: "Aug 2025",
      claim: "Data center load projected: 800MW in 2026 → 14.4GW by 2034",
      source: (
        <>
          <SourceChip id="capitalstar-load" /> The 800MW-in-2026 figure is checkable against
          real PJM load data (see the note below on where that comparison lives).
        </>
      ),
    },
    {
      date: "Q4 2025",
      claim: "25.2 GW in signed agreements",
      source: <SourceChip id="dcd-ppl-pipeline" />,
    },
    {
      date: "Jan 2026",
      claim: "PJM's own forecast for PPL's territory summer peak: 7,300 MW → 12,000 MW",
      source: (
        <>
          <SourceChip id="pjm-load-2026" /> This one is PJM&apos;s independently published number,
          not PPL&apos;s own PR.
        </>
      ),
    },
    {
      date: "Q2 2026",
      claim: "31.8 GW pipeline · 11 GW signed · 6.5 GW under construction",
      source: (
        <>
          <SourceChip id="investing-ppl-q2" /> Joint venture with Blackstone (Invitium Energy) has
          secured sites for 8&ndash;14 GW of new generation.
        </>
      ),
    },
  ];

  return (
    <main className="mx-auto w-full max-w-[680px] px-4 py-14">
      <SectionRail items={RAIL} width="narrow" />
      <h1 id="overview" className="mb-3 text-[2.2rem] leading-tight font-bold text-balance">
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
          <Cite id="investing-ppl-q2" nums={n} />
        </div>
        <div>
          <b className="text-[1.3rem] tabular-nums" style={{ color: "var(--ink-1)" }}>
            {eiaReadingCount.toLocaleString("en-US")}
          </b>{" "}
          real EIA-930 readings behind this page
        </div>
      </div>

      <section id="why-this-exists" className="mb-10">
        <h2 className="mb-3 text-xl font-bold">Why this exists</h2>
        <p>
          This started as a real-time anomaly detector on the PJM grid: an isolation forest
          scoring forecast residuals across five Pennsylvania utility zones, built and verified
          end to end (ingestion, Kafka streaming, Kubernetes, CI). That pipeline is live.
          See the <Link href="/demand">PJM demand</Link> page for real output from it, not mockups.
        </p>
        <p>
          What it&apos;s turning into is more specific. PJM&apos;s wholesale power market is
          short on supply, and PJM&apos;s own capacity auction is pointing at one cause: AI data
          center demand.
          <Cite id="utilitydive-capacity" nums={n} />
          <Cite id="ieefa-capacity" nums={n} /> Pennsylvania utilities have made public, dated,
          numbered claims about how much of that demand is coming to their territory. Those
          claims are checkable against real metered data. This page is the first pass at doing
          that. The <Link href="/map">PA map</Link> shows where publicly reported data center
          projects sit relative to each utility.
        </p>
      </section>

      <section id="pipeline" className="mb-10">
        <h2 className="mb-3 text-xl font-bold">PPL&apos;s pipeline, quarter by quarter</h2>
        <p>
          PPL Electric covers roughly 29 counties across central and eastern Pennsylvania,
          stretching from Lancaster through the Lehigh Valley to Scranton/Wilkes-Barre.
          It&apos;s the one PA utility Pennsylvania&apos;s own Public Utility Commission names
          as facing significant data-center-driven demand growth; the other four zones this
          project tracks are explicitly not.
          <Cite id="puc-epo" nums={n} />
        </p>
        <div className="mt-4 flex flex-col">
          {timeline.map((item) => (
            <div
              key={item.date}
              className="grid grid-cols-[5.5rem_1fr] gap-x-5 border-t py-4 first:border-t-0"
              style={{ borderColor: "var(--border)" }}
            >
              <div className="pt-0.5 text-[0.85rem] font-bold tabular-nums" style={{ color: "var(--ink-2)" }}>
                {item.date}
              </div>
              <div>
                <div className="mb-1.5 font-semibold">{item.claim}</div>
                <div className="text-[0.88rem] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                  {item.source}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section id="caveats" className="mb-10">
        <h2 className="mb-3 text-xl font-bold">Why these numbers might not mean what they say</h2>
        <div
          className="rounded-lg border p-5"
          style={{ borderColor: "color-mix(in srgb, var(--orange) 55%, var(--border))", background: "var(--surface-1)" }}
        >
          <h3 className="mb-1 font-bold">The duplicate-request problem</h3>
          <p className="mb-0">
            A July 2025 London Economics International analysis, prepared for the Southern
            Environmental Law Center,
            <Cite id="lei-report" nums={n} /> argues pipeline figures like these are structurally
            inflated: developers routinely file interconnection requests at multiple candidate
            sites simultaneously while deciding where to actually build, so the same project can
            show up in several utilities&apos; &quot;pipeline&quot; totals at once. The same
            report flags equipment and chip supply bottlenecks as a separate reason real load
            growth could come in well below what&apos;s announced. Lawrence Berkeley National
            Laboratory&apos;s literature review summarizes the same findings.
            <Cite id="lbnl-llr" nums={n} />
          </p>
        </div>
        <p className="mt-5">
          This is exactly why an accountability check is worth building, not a reason to skip
          it. There are two competing public stories: explosive, utility-reported growth, and
          analyst skepticism that it&apos;s overstated. Real metered demand is the only neutral
          referee between them.
        </p>
      </section>

      <section
        id="measured-comparison"
        className="mb-10 rounded-lg border p-5"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        <h2 className="mb-2 text-lg font-bold">Where the real measured comparison lives</h2>
        <p className="mb-0">
          The actual PPL load-vs-promises comparison is built and running on real data, but it
          isn&apos;t shown here. PJM&apos;s Data Miner 2 API terms prohibit non-member
          redistribution of data derived from it, and the comparison depends on zone-level LMP
          and load readings from that feed. It&apos;s being tracked internally, not abandoned.
          Making it public depends on resolving a PJM data redistribution license, a separate
          piece of work from the pipeline itself.
        </p>
      </section>

      <section id="limits" className="mb-10">
        <h2 className="mb-3 text-xl font-bold">What this does and doesn&apos;t prove</h2>
        <p>
          <b>How the detection works:</b> an isolation forest scores the residual between actual
          demand and a seasonal-naive forecast (same hour, same day of week, prior cycle) plus
          rolling context, fit only on data through mid-2025 and evaluated on a later window it
          never trained on. There are no real anomaly labels for this data; detector quality is
          measured by injecting synthetic anomalies into held-out data and checking recall at a
          fixed false-positive budget. That&apos;s a check on the method, not a guarantee about
          any specific real event.
        </p>
        <p>
          <b>Why this is a PPL story, not a five-zone story:</b> Pennsylvania&apos;s PUC
          explicitly says the other four zones tracked here aren&apos;t expecting significant
          data-center impact.
          <Cite id="puc-epo" nums={n} /> Treating this as a statewide comparison would overstate
          what the data supports.
        </p>
        <p>
          <b>Correlation, never causation:</b> PA demand can move for reasons that have nothing
          to do with data centers: weather, broader electrification, EV adoption, ordinary
          industrial growth. Nothing here is designed or intended to prove a single cause.
        </p>
      </section>

      <ReferenceList ids={REF_IDS} nums={n} heading="Every claim above, linked" />

      <footer className="pt-8 pb-12 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        {STATIC_DEMO ? (
          <>
            Snapshot taken {SNAPSHOT_LABEL}. Numbers on this page and on{" "}
            <Link href="/demand">/demand</Link> are frozen at that moment. The live site refreshes
            on every request, read straight from Postgres.
          </>
        ) : (
          <>
            Live pipeline. Numbers on this page and on <Link href="/demand">/demand</Link> refresh
            on every request, read straight from Postgres.
          </>
        )}
      </footer>
    </main>
  );
}
