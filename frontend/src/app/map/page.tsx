import Link from "next/link";
import { PaMap } from "@/components/PaMap";
import { SourceChip } from "@/components/Sources";
import { STATIC_DEMO } from "@/lib/staticDemo";

// Public route. Everything on this page is public geography (county lines, HIFLD utility
// territories) plus publicly reported data center projects. No PJM Data Miner 2 figure is
// fetched or rendered here: the zone overlay lives at /private/map, behind the passcode.

export const metadata = {
  title: "PA data center map | Grid Watch",
  description: "Publicly reported data center projects in Pennsylvania, against county lines and utility territories.",
};

export default function MapPage() {
  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-12">
      <h1 className="mb-4 text-3xl font-bold">Pennsylvania data center map</h1>
      <p className="mb-8 max-w-[680px]" style={{ color: "var(--ink-2)" }}>
        Publicly reported data center projects, shown against county lines and the territories of
        the utilities that serve them. Select a project, county, or utility for details and
        sources.
      </p>

      <PaMap />

      <section className="mt-12 max-w-[680px]" aria-labelledby="about-data">
        <h2 id="about-data" className="mb-3 text-xl font-bold">
          About this data
        </h2>
        <p>
          <b>A curated list, not a registry.</b> Each project was read from news coverage, a
          company release, or local reporting, and lists the sources it came from. There is no
          authoritative public registry of these projects to draw from, so a project missing here
          may simply not have been found.
        </p>
        <p>
          <b>Locations are approximate.</b> A marker sits at or near the named site where one
          was reported, otherwise within the township, borough or city. Statuses change quickly,
          so each project shows the date of the reporting behind it. A hollow marker means the
          project was denied or abandoned.
        </p>
        <p>
          <b>Figures are not comparable.</b> Some entries report a power agreement, some a power
          plant&apos;s output, some floor area or investment. They are shown as reported and never
          added together.
        </p>
        <p>
          <b>Boundaries.</b> Utility territories come from HIFLD&apos;s retail service territory
          layer, republished by Penn State&apos;s PASDA, and are approximate. County lines are
          derived from U.S. Census data.
        </p>
        <p className="flex flex-wrap items-center gap-2">
          <SourceChip href="https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=9056" label="PASDA: Electric Retail Service Territories" />
          <SourceChip href="https://github.com/plotly/datasets/blob/master/geojson-counties-fips.json" label="County geometry (Census-derived)" />
        </p>
        <p>
          <b>Private overlay.</b> Signed-in users can shade the five PJM utility zones with price
          and anomaly figures on a private map (passcode required).{" "}
          {STATIC_DEMO ? (
            "That part of the site is not included in this static demo."
          ) : (
            <Link href="/private/map">Open the private map</Link>
          )}
        </p>
      </section>
    </main>
  );
}
