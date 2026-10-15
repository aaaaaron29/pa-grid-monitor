import { PA_UTILITIES } from "@/data/paGeo";
import type { DataCenter } from "@/data/dataCenters";
import { SourceChip } from "@/components/Sources";
import { STATUS, StatusIcon } from "@/components/mapStatus";

const fmt = (n: number) => n.toLocaleString("en-US");
const miles = (r: number) => (r === 0.5 ? "½ mi" : `${r} mi`);
const MAX_PLACES = 8;

function utilityName(id: string | null) {
  return PA_UTILITIES.find((u) => u.id === id)?.name ?? "Other or unmapped utility";
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h4 className="mt-5 mb-1.5 text-sm font-bold">{children}</h4>;
}

/** Everything the map knows about one project. Proximity is stated as proximity: how many
 *  people live near the marker, never a prediction of who will be affected. */
export function DcDetail({
  dc,
  rings,
  onRings,
  onBack,
  onCounty,
  onUtility,
}: {
  dc: DataCenter;
  rings: boolean;
  onRings: (v: boolean) => void;
  onBack: () => void;
  onCounty: (fips: string) => void;
  onUtility: (id: string) => void;
}) {
  const precision =
    dc.precision === "site"
      ? "Placed at or near the named site."
      : "Approximate: placed within the township, borough or city.";
  const places = dc.places ?? [];

  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex items-center gap-1 rounded text-[0.85rem] font-medium hover:text-[var(--ink-1)]"
        style={{ color: "var(--ink-2)" }}
      >
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M7.5 2 3.5 6l4 4" />
        </svg>
        All projects
      </button>
      <h3 className="mb-0.5 text-lg leading-snug font-bold">{dc.name}</h3>
      <p className="mb-2 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        {dc.place}
      </p>
      <p className="mb-3 flex items-center gap-1.5 text-[0.85rem] font-semibold text-[var(--ink-1)]">
        <StatusIcon status={dc.statusCategory} />
        {STATUS[dc.statusCategory].label}
      </p>
      <p className="mb-3 text-[0.9rem]">{dc.summary}</p>
      <dl className="mb-1 grid grid-cols-1 gap-px overflow-hidden rounded-lg border text-[0.85rem]" style={{ background: "var(--border)", borderColor: "var(--border)" }}>
        {dc.figures.map((f) => (
          <div key={f.label} className="flex items-baseline justify-between gap-3 p-2.5" style={{ background: "var(--surface-1)" }}>
            <dt style={{ color: "var(--ink-2)" }}>
              {f.label}
              {f.note ? <span className="block text-[0.75rem]">{f.note}</span> : null}
            </dt>
            <dd className="text-right font-bold tabular-nums text-[var(--ink-1)]">{f.value}</dd>
          </div>
        ))}
      </dl>

      <Heading>Status</Heading>
      <p className="mb-1 text-[0.9rem]">{dc.status}</p>
      <p className="text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
        As of: {dc.asOf}
      </p>

      <Heading>Who and what is nearby</Heading>
      {dc.exposure ? (
        <>
          <table className="w-full text-[0.85rem] tabular-nums">
            <caption className="sr-only">People and homes near the marker, from the 2020 Census</caption>
            <thead>
              <tr style={{ color: "var(--ink-2)" }}>
                <th scope="col" className="py-1 text-left font-semibold">Within</th>
                <th scope="col" className="py-1 text-right font-semibold">People</th>
                <th scope="col" className="py-1 text-right font-semibold">Homes</th>
              </tr>
            </thead>
            <tbody>
              {dc.exposure.radiiMiles.map((r, i) => (
                <tr key={r} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="py-1">{miles(r)}</td>
                  <td className="py-1 text-right font-semibold text-[var(--ink-1)]">{fmt(dc.exposure!.people[i])}</td>
                  <td className="py-1 text-right">{fmt(dc.exposure!.homes[i])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {dc.exposure.nearestHomesMiles !== null && (
            <p className="mt-2 text-[0.85rem]">
              Nearest homes: about <b>{dc.exposure.nearestHomesMiles} mi</b> from the marker.
            </p>
          )}
          <p className="mt-2 text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
            2020 Census counts{dc.exposure.states.length > 1 ? ` (including ${dc.exposure.states.filter((s) => s !== "PA").join(", ")} across the state line)` : ""}.
          </p>

          <h5 className="mt-4 mb-1 text-[0.85rem] font-semibold">
            Schools, hospitals, nursing homes and child care within 1 mile
          </h5>
          {places.length === 0 ? (
            <p className="text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
              None listed in the federal facility layers.
            </p>
          ) : (
            <ul className="text-[0.85rem]">
              {places.slice(0, MAX_PLACES).map((p) => (
                <li key={`${p.kind}-${p.name}`} className="flex items-baseline justify-between gap-3 py-0.5">
                  <span>
                    {p.name} <span style={{ color: "var(--ink-2)" }}>({p.kind.toLowerCase()})</span>
                  </span>
                  <span className="tabular-nums" style={{ color: "var(--ink-2)" }}>{p.miles} mi</span>
                </li>
              ))}
              {places.length > MAX_PLACES && (
                <li className="py-0.5" style={{ color: "var(--ink-2)" }}>and {places.length - MAX_PLACES} more</li>
              )}
            </ul>
          )}
          <label className="mt-3 flex items-center gap-2 text-[0.85rem]">
            <input type="checkbox" checked={rings} onChange={(e) => onRings(e.target.checked)} />
            Show 1-mile and 5-mile rings (zooms the map)
          </label>
        </>
      ) : (
        <p className="text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
          Not measured. This project is only located to a township, borough or city, which is too
          coarse to measure distances from.
        </p>
      )}
      <p
        className="mt-3 rounded-md border p-2.5 text-[0.8rem]"
        style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}
      >
        <b>Proximity is not impact.</b> These figures show who lives near the marker. Whether
        anyone is affected depends on cooling, backup generators, noise and water use, which most
        projects have not disclosed. Distances run from the marker, not the property line.
      </p>

      <Heading>Power</Heading>
      {dc.nearestPlant ? (
        <p className="text-[0.9rem]">
          {dc.nearestPlant.miles < 0.3
            ? `At or beside the ${dc.nearestPlant.name} plant`
            : `Nearest operating plant of 100 MW or more: ${dc.nearestPlant.name}, ${dc.nearestPlant.miles} mi away`}{" "}
          ({dc.nearestPlant.fuel}
          {dc.nearestPlant.mw ? `, ${fmt(dc.nearestPlant.mw)} MW` : ""}).
        </p>
      ) : (
        <p className="text-[0.85rem]" style={{ color: "var(--ink-2)" }}>Not measured.</p>
      )}
      {dc.locatedBy && (
        <p className="mt-1 text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
          {dc.locatedBy}. Plant status and capacity come from a federal layer that can lag reality.
        </p>
      )}

      <Heading>Local response, as reported</Heading>
      {dc.community.length === 0 ? (
        <p className="text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
          Nothing found in the sources read. That does not mean there has been no response.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {dc.community.map((c) => (
            <li key={c.text} className="text-[0.85rem]">
              <p>{c.text}</p>
              <p className="mt-1 flex flex-wrap items-center gap-1.5" style={{ color: "var(--ink-2)" }}>
                <SourceChip href={c.source.url} label={c.source.label} />
                <span className="text-[0.75rem]">{c.asOf}</span>
              </p>
            </li>
          ))}
        </ul>
      )}

      <Heading>Where it sits</Heading>
      <p className="mb-1 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        {dc.county ? (
          <>
            <button type="button" className="underline underline-offset-2 hover:text-[var(--blue)]" onClick={() => onCounty(dc.countyFips!)}>
              {dc.county} County
            </button>
            {dc.utilityId ? (
              <>
                {", "}
                <button type="button" className="underline underline-offset-2 hover:text-[var(--blue)]" onClick={() => onUtility(dc.utilityId!)}>
                  {utilityName(dc.utilityId)} territory
                </button>
              </>
            ) : null}
            . {precision}
          </>
        ) : (
          precision
        )}
      </p>

      <Heading>Sources</Heading>
      <div className="flex flex-wrap gap-1.5">
        {dc.sources.map((s) => (
          <SourceChip key={s.url} href={s.url} label={s.label} />
        ))}
      </div>
    </div>
  );
}
