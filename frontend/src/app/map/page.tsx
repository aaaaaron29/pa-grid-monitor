import Link from "next/link";
import { PaMap } from "@/components/PaMap";
import { SourceChip } from "@/components/Sources";
import { STATIC_DEMO } from "@/lib/staticDemo";
import { SectionRail } from "@/components/SectionRail";

const RAIL = [
  { id: "map-tool", label: "Map and project details" },
  { id: "all-projects", label: "All projects" },
  { id: "about-data", label: "About this data" },
];

// Public route. Everything on this page is public geography (county lines, HIFLD utility
// territories, HIFLD power plants and facilities), Census 2020 counts, and publicly reported
// data center projects. No PJM Data Miner 2 figure is fetched or rendered here: the zone
// overlay lives at /private/map, behind the passcode.

export const metadata = {
  title: "PA data center map | Grid Watch",
  description:
    "Publicly reported data center projects in Pennsylvania: status, who lives nearby, and the nearest power plant.",
};

export default function MapPage() {
  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-12">
      <SectionRail items={RAIL} width="wide" />
      <h1 className="mb-4 text-3xl font-bold">Pennsylvania data center map</h1>
      <p className="mb-8 max-w-[680px]" style={{ color: "var(--ink-2)" }}>
        Publicly reported data center projects, shown against county lines and the territories of
        the utilities that serve them. Filter by status, search, and select a project to see how
        many people and which schools and hospitals are near it, how it is going locally, and
        where its sources are.
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
          <b>Statuses.</b> A project is Announced, Under local review, Approved for a first phase,
          Under construction, Rejected locally, or Abandoned. Each stage has its own marker shape
          as well as a color. Statuses change quickly, so each project shows the date of the
          reporting behind it, and an announcement that has had no news since is still listed as
          announced.
        </p>
        <p>
          <b>Who lives nearby.</b> For projects placed at a specific site, the panel counts people
          and homes within half a mile to five miles of the marker, using 2020 Census block
          counts, and lists schools, hospitals, nursing homes and child care facilities within a
          mile. Existing housing only: planned developments are not counted. Census blocks are
          assigned by their center point, so counts near a ring edge are approximate, and the
          Census adds noise to small blocks to protect privacy. Projects located only to a
          township, borough or city show &ldquo;not measured&rdquo;, because that is too coarse
          to measure distance from.
        </p>
        <p>
          <b>Proximity is not impact.</b> These figures describe who lives near a marker. They are
          not a forecast of noise, water use, emissions or rates for anyone, and the map has no
          risk score. Distances run from the marker, which is placed from reporting and is not a
          surveyed property line.
        </p>
        <p>
          <b>Local response.</b> Notes on public comment, votes and opposition are included only
          where a source read for this map reported them, with a link. Where the panel says
          nothing was found, that means the sources read did not cover it.
        </p>
        <p>
          <b>Power plants.</b> The optional layer shows operating plants of 100 MW or more from
          HIFLD, a federal layer that can lag reality. Where a project is reported to be at a
          named plant, its marker is placed there.
        </p>
        <p>
          <b>Figures are not comparable.</b> Some entries report a power agreement, some a power
          plant&apos;s output, some floor area or investment. They are shown as reported and never
          added together.
        </p>
        <p>
          <b>Boundaries and sources.</b> Utility territories, power plants and facilities come from
          HIFLD, republished by Penn State&apos;s PASDA, and are approximate. County lines are
          derived from U.S. Census data. Population and housing counts are from the 2020 Census
          redistricting files; blocks in New Jersey, Maryland and other neighboring states are
          included for projects near the state line.
        </p>
        <p className="flex flex-wrap items-center gap-2">
          <SourceChip href="https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=9056" label="PASDA: Electric Retail Service Territories" />
          <SourceChip href="https://mapservices.pasda.psu.edu/server/rest/services/pasda/HIFLD_FEMA_PA/MapServer" label="PASDA: HIFLD plants and facilities" />
          <SourceChip href="https://www.census.gov/programs-surveys/decennial-census/about/rdo/summary-files.html" label="Census 2020 redistricting files" />
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
