"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { PA_COUNTIES, PA_UTILITIES, PA_VIEWBOX, type PaUtility, type ZoneName } from "@/data/paGeo";
import { DATA_CENTERS, DATA_CENTERS_REVIEWED, type DataCenter } from "@/data/dataCenters";
import { SourceChip } from "@/components/Sources";

// Public geography + publicly reported projects only. PJM zone figures reach this component
// ONLY through the `zoneStats` prop, which /private/map alone supplies, so the public /map
// page can never render them.

export interface ZoneStat {
  currentPrice: number | null;
  peak24hPrice: number | null;
  anomalies7d: number;
  freshnessMinutes: number | null;
}

type Selection = { kind: "dc" | "county" | "utility"; id: string } | null;
type Metric = "none" | "peak" | "current" | "anomalies";

const UTILITY_COLOR: Record<string, string> = {
  ppl: "var(--orange)",
  peco: "var(--blue)",
  "met-ed": "var(--aqua)",
  penelec: "var(--red)",
  duquesne: "var(--warning)",
};

const OTHER_COLOR = "var(--ink-muted)";

// Breathing room so edge markers and strokes are never cut by the frame.
const PAD = 24;
const VB_W = PA_VIEWBOX.w + PAD * 2;
const VB_H = PA_VIEWBOX.h + PAD * 2;

function fmtPrice(v: number | null) {
  if (v == null) return "n/a";
  return (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function utilityName(id: string | null) {
  return PA_UTILITIES.find((u) => u.id === id)?.name ?? "Other or unmapped utility";
}

export function PaMap({ zoneStats }: { zoneStats?: Partial<Record<ZoneName, ZoneStat>> }) {
  const isPrivate = Boolean(zoneStats);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(700);
  const [selection, setSelection] = useState<Selection>(null);
  const [hoverCounty, setHoverCounty] = useState<string | null>(null);
  const [hoverDc, setHoverDc] = useState<string | null>(null);
  const [showUtilities, setShowUtilities] = useState(true);
  const [showDc, setShowDc] = useState(true);
  const [metric, setMetric] = useState<Metric>("none");

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(280, el.getBoundingClientRect().width));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Size markers and strokes in screen pixels, whatever width the map is drawn at.
  const u = VB_W / width;

  const countyByFips = useMemo(() => new Map(PA_COUNTIES.map((c) => [c.fips, c])), []);
  const dcByCounty = useMemo(() => {
    const m = new Map<string, DataCenter[]>();
    for (const dc of DATA_CENTERS) {
      if (!dc.countyFips) continue;
      m.set(dc.countyFips, [...(m.get(dc.countyFips) ?? []), dc]);
    }
    return m;
  }, []);
  const countiesWithDc = new Set(DATA_CENTERS.map((d) => d.countyFips).filter(Boolean)).size;

  // Private overlay: shade zone utilities by one metric, scaled to the max across the five zones.
  const metricValue = (uObj: PaUtility): number | null => {
    if (!zoneStats || !uObj.zone) return null;
    const s = zoneStats[uObj.zone];
    if (!s) return null;
    if (metric === "peak") return s.peak24hPrice;
    if (metric === "current") return s.currentPrice;
    if (metric === "anomalies") return s.anomalies7d;
    return null;
  };
  const metricMax = useMemo(() => {
    if (!zoneStats || metric === "none") return 0;
    const vals = PA_UTILITIES.map((x) => {
      const s = x.zone ? zoneStats[x.zone] : undefined;
      if (!s) return 0;
      const v = metric === "peak" ? s.peak24hPrice : metric === "current" ? s.currentPrice : s.anomalies7d;
      return Math.abs(v ?? 0);
    });
    return Math.max(...vals, 0);
  }, [zoneStats, metric]);

  const territoryFill = (x: PaUtility): { fill: string; opacity: number } => {
    const dim = selection?.kind === "utility" && selection.id !== x.id ? 0.35 : 1;
    if (isPrivate && metric !== "none") {
      const v = metricValue(x);
      if (v == null) return { fill: OTHER_COLOR, opacity: 0.1 * dim };
      const t = metricMax > 0 ? Math.min(1, Math.abs(v) / metricMax) : 0;
      return { fill: "var(--blue)", opacity: (0.12 + 0.68 * t) * dim };
    }
    const color = UTILITY_COLOR[x.id];
    return color ? { fill: color, opacity: 0.3 * dim } : { fill: OTHER_COLOR, opacity: 0.12 * dim };
  };

  const select = (s: Selection) => setSelection((cur) => (cur && s && cur.kind === s.kind && cur.id === s.id ? null : s));

  const hoverText = hoverDc
    ? DATA_CENTERS.find((d) => d.id === hoverDc)?.name
    : hoverCounty
      ? `${countyByFips.get(hoverCounty)?.name} County`
      : null;
  const hoverPos = hoverDc
    ? DATA_CENTERS.find((d) => d.id === hoverDc)
    : hoverCounty
      ? countyByFips.get(hoverCounty)
      : null;
  const hoverX = hoverPos ? ("x" in hoverPos ? hoverPos.x : hoverPos.cx) : 0;
  const hoverY = hoverPos ? ("y" in hoverPos ? hoverPos.y : hoverPos.cy) : 0;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_21rem]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Toggle pressed={showUtilities} onClick={() => setShowUtilities((v) => !v)} label="Utility territories" />
          <Toggle pressed={showDc} onClick={() => setShowDc((v) => !v)} label="Data center projects" />
          {isPrivate && (
            <label className="ml-auto flex items-center gap-2 text-sm" style={{ color: "var(--ink-2)" }}>
              Shade zones by
              <select
                value={metric}
                onChange={(e) => setMetric(e.target.value as Metric)}
                className="rounded-md border px-2 py-1"
                style={{ borderColor: "var(--baseline)", background: "var(--surface-1)", color: "var(--ink-1)" }}
              >
                <option value="none">Utility colors</option>
                <option value="current">Current LMP</option>
                <option value="peak">24h peak LMP</option>
                <option value="anomalies">Anomalies (7d)</option>
              </select>
            </label>
          )}
        </div>

        <div
          ref={wrapRef}
          className="relative overflow-hidden rounded-[10px] border"
          style={{ background: "var(--surface-1)", borderColor: "var(--border)" }}
        >
          <svg
            viewBox={`${-PAD} ${-PAD} ${VB_W} ${VB_H}`}
            className="block h-auto w-full"
            role="group"
            aria-label="Map of Pennsylvania counties, utility territories, and reported data center projects"
          >
            <defs>
              <clipPath id="pa-clip">
                {PA_COUNTIES.map((c) => (
                  <path key={c.fips} d={c.d} />
                ))}
              </clipPath>
            </defs>

            {showUtilities && (
              <g clipPath="url(#pa-clip)" style={{ pointerEvents: "none" }}>
                {PA_UTILITIES.map((x) => {
                  const f = territoryFill(x);
                  return (
                    <path
                      key={x.id}
                      d={x.d}
                      fill={f.fill}
                      fillOpacity={f.opacity}
                      fillRule="evenodd"
                      stroke={f.fill}
                      strokeOpacity={Math.min(1, f.opacity + 0.35)}
                      strokeWidth={(selection?.kind === "utility" && selection.id === x.id ? 2.4 : 1) * u}
                    />
                  );
                })}
              </g>
            )}

            <g>
              {PA_COUNTIES.map((c) => {
                const selected = selection?.kind === "county" && selection.id === c.fips;
                return (
                  <path
                    key={c.fips}
                    d={c.d}
                    fill={hoverCounty === c.fips || selected ? "var(--ink-1)" : "transparent"}
                    fillOpacity={selected ? 0.12 : 0.07}
                    stroke={selected ? "var(--ink-1)" : "var(--baseline)"}
                    strokeWidth={(selected ? 1.8 : 0.8) * u}
                    strokeLinejoin="round"
                    style={{ cursor: "pointer" }}
                    onPointerEnter={() => setHoverCounty(c.fips)}
                    onPointerLeave={() => setHoverCounty((cur) => (cur === c.fips ? null : cur))}
                    onClick={() => select({ kind: "county", id: c.fips })}
                  />
                );
              })}
            </g>

            {showDc &&
              DATA_CENTERS.map((dc) => {
                const selected = selection?.kind === "dc" && selection.id === dc.id;
                return (
                  <g
                    key={dc.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${dc.name}, ${dc.place}`}
                    aria-pressed={selected}
                    style={{ cursor: "pointer", outline: "none" }}
                    onPointerEnter={() => setHoverDc(dc.id)}
                    onPointerLeave={() => setHoverDc((cur) => (cur === dc.id ? null : cur))}
                    onFocus={() => setHoverDc(dc.id)}
                    onBlur={() => setHoverDc((cur) => (cur === dc.id ? null : cur))}
                    onClick={(e) => {
                      e.stopPropagation();
                      select({ kind: "dc", id: dc.id });
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        select({ kind: "dc", id: dc.id });
                      }
                    }}
                  >
                    <circle cx={dc.x} cy={dc.y} r={16 * u} fill="transparent" />
                    {(selected || hoverDc === dc.id) && (
                      <circle cx={dc.x} cy={dc.y} r={11 * u} fill="none" stroke="var(--ink-1)" strokeWidth={1.5 * u} />
                    )}
                    <circle
                      cx={dc.x}
                      cy={dc.y}
                      r={dc.ended ? 5 * u : 6 * u}
                      fill={dc.ended ? "var(--surface-1)" : "var(--ink-1)"}
                      stroke={dc.ended ? "var(--ink-1)" : "var(--surface-1)"}
                      strokeWidth={dc.ended ? 2 * u : 1.5 * u}
                    />
                  </g>
                );
              })}
          </svg>

          {hoverText && (
            <div
              className="pointer-events-none absolute z-10 rounded-md px-2 py-1 text-xs font-medium whitespace-nowrap shadow-md"
              style={{
                background: "var(--ink-1)",
                color: "var(--page)",
                left: `${((hoverX + PAD) / VB_W) * 100}%`,
                top: `${((hoverY + PAD) / VB_H) * 100}%`,
                transform: `translate(${hoverX > PA_VIEWBOX.w * 0.7 ? "-100%" : hoverX < PA_VIEWBOX.w * 0.15 ? "0" : "-50%"}, calc(-100% - 14px))`,
              }}
            >
              {hoverText}
            </div>
          )}
        </div>

        <Legend isPrivate={isPrivate} metric={metric} metricMax={metricMax} selection={selection} onSelectUtility={(id) => select({ kind: "utility", id })} />
      </div>

      <aside
        className="min-w-0 rounded-[10px] border p-5 lg:self-start"
        style={{ background: "var(--surface-1)", borderColor: "var(--border)" }}
        aria-live="polite"
      >
        <Panel
          selection={selection}
          setSelection={setSelection}
          select={select}
          dcByCounty={dcByCounty}
          countiesWithDc={countiesWithDc}
          zoneStats={zoneStats}
        />
      </aside>
    </div>
  );
}

function Toggle({ pressed, onClick, label }: { pressed: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className="rounded-full border px-3.5 py-1.5 text-sm font-semibold transition-colors"
      style={{
        borderColor: pressed ? "var(--ink-1)" : "var(--baseline)",
        background: pressed ? "var(--ink-1)" : "var(--surface-1)",
        color: pressed ? "var(--page)" : "var(--ink-2)",
      }}
    >
      {label}
    </button>
  );
}

function Legend({
  isPrivate,
  metric,
  metricMax,
  selection,
  onSelectUtility,
}: {
  isPrivate: boolean;
  metric: Metric;
  metricMax: number;
  selection: Selection;
  onSelectUtility: (id: string) => void;
}) {
  const zoneUtilities = PA_UTILITIES.filter((x) => UTILITY_COLOR[x.id]);
  const metricLabel: Record<Metric, string> = {
    none: "",
    current: "Current LMP",
    peak: "24h peak LMP",
    anomalies: "Anomalies (7d)",
  };
  return (
    <div className="mt-3 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {zoneUtilities.map((x) => {
          const active = selection?.kind === "utility" && selection.id === x.id;
          return (
            <button
              key={x.id}
              type="button"
              onClick={() => onSelectUtility(x.id)}
              aria-pressed={active}
              className="flex items-center gap-1.5 rounded py-0.5 hover:text-[var(--ink-1)]"
              style={{ color: active ? "var(--ink-1)" : undefined, fontWeight: active ? 600 : 400 }}
            >
              <span
                className="inline-block h-3 w-3 rounded-sm border"
                style={{
                  background: isPrivate && metric !== "none" ? "var(--blue)" : UTILITY_COLOR[x.id],
                  opacity: isPrivate && metric !== "none" ? 0.45 : 0.55,
                  borderColor: "var(--baseline)",
                }}
              />
              {x.name}
            </button>
          );
        })}
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border" style={{ background: OTHER_COLOR, opacity: 0.3, borderColor: "var(--baseline)" }} />
          Other utilities
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-full" style={{ background: "var(--ink-1)" }} />
          Reported project
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-full border-2" style={{ borderColor: "var(--ink-1)", background: "var(--surface-1)" }} />
          Denied or abandoned
        </span>
      </div>
      {isPrivate && metric !== "none" && (
        <div className="mt-2 flex items-center gap-2 text-[0.8rem]">
          <span>{metricLabel[metric]}, low</span>
          <span
            className="h-2 w-28 rounded"
            style={{ background: "linear-gradient(to right, color-mix(in srgb, var(--blue) 12%, transparent), color-mix(in srgb, var(--blue) 80%, transparent))" }}
          />
          <span>
            high ({metric === "anomalies" ? Math.round(metricMax) : fmtPrice(metricMax)})
          </span>
        </div>
      )}
    </div>
  );
}

function Panel({
  selection,
  setSelection,
  select,
  dcByCounty,
  countiesWithDc,
  zoneStats,
}: {
  selection: Selection;
  setSelection: (s: Selection) => void;
  select: (s: Selection) => void;
  dcByCounty: Map<string, DataCenter[]>;
  countiesWithDc: number;
  zoneStats?: Partial<Record<ZoneName, ZoneStat>>;
}) {
  if (selection?.kind === "dc") {
    const dc = DATA_CENTERS.find((d) => d.id === selection.id);
    if (dc) return <DcDetail dc={dc} onBack={() => setSelection(null)} select={select} />;
  }

  if (selection?.kind === "county") {
    const county = PA_COUNTIES.find((c) => c.fips === selection.id);
    const dcs = dcByCounty.get(selection.id) ?? [];
    return (
      <div>
        <BackButton onClick={() => setSelection(null)} />
        <h3 className="mb-1 text-lg font-bold">{county?.name} County</h3>
        {dcs.length === 0 ? (
          <p className="text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
            No project in this county is tracked here. That does not mean none exist: this is a
            curated list from public reporting, not a complete registry.
          </p>
        ) : (
          <>
            <p className="mb-3 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
              {dcs.length} reported {dcs.length === 1 ? "project" : "projects"} in this county.
            </p>
            <ProjectList dcs={dcs} select={select} showUtility />
          </>
        )}
      </div>
    );
  }

  if (selection?.kind === "utility") {
    const x = PA_UTILITIES.find((v) => v.id === selection.id);
    if (!x) return null;
    const dcs = DATA_CENTERS.filter((d) => d.utilityId === x.id);
    const zs = x.zone && zoneStats ? zoneStats[x.zone] : undefined;
    return (
      <div>
        <BackButton onClick={() => setSelection(null)} />
        <h3 className="mb-1 text-lg font-bold">{x.name}</h3>
        <p className="mb-3 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
          {x.holding}. About {x.customers.toLocaleString("en-US")} customers (HIFLD).
        </p>
        {zs && (
          <dl
            className="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border text-[0.85rem]"
            style={{ background: "var(--border)", borderColor: "var(--border)" }}
          >
            <Stat label="Current LMP" value={fmtPrice(zs.currentPrice)} />
            <Stat label="24h peak LMP" value={fmtPrice(zs.peak24hPrice)} />
            <Stat label="Anomalies (7d)" value={String(zs.anomalies7d)} />
            <Stat label="Freshness" value={zs.freshnessMinutes != null ? `${zs.freshnessMinutes}m` : "n/a"} />
          </dl>
        )}
        {x.id === "ppl" && (
          <p className="mb-4 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
            PPL reports an advanced-stage pipeline of 31.8 GW (Q2 2026). <SourceChip id="investing-ppl-q2" />{" "}
            The projects below are individually reported sites, and this map does not attempt to
            reconcile them with that figure.
          </p>
        )}
        <h4 className="mb-2 text-sm font-bold">Reported projects in this territory</h4>
        {dcs.length === 0 ? (
          <p className="text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
            None tracked here. This is not a complete registry.
          </p>
        ) : (
          <ProjectList dcs={dcs} select={select} />
        )}
      </div>
    );
  }

  // Default view
  const byUtility = PA_UTILITIES.map((x) => ({ x, n: DATA_CENTERS.filter((d) => d.utilityId === x.id).length })).filter((r) => r.n > 0);
  return (
    <div>
      <h3 className="mb-1 text-lg font-bold">
        {DATA_CENTERS.length} reported projects in {countiesWithDc} counties
      </h3>
      <p className="mb-3 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        Select a project, county, or utility to see details. {DATA_CENTERS.filter((d) => d.ended).length} of these have been
        denied or abandoned. Reviewed {DATA_CENTERS_REVIEWED}.
      </p>
      <ProjectList dcs={DATA_CENTERS} select={select} showUtility />
      <h4 className="mt-5 mb-2 text-sm font-bold">By utility territory</h4>
      <ul className="flex flex-col gap-1 text-[0.9rem]">
        {byUtility.map(({ x, n }) => (
          <li key={x.id}>
            <button
              type="button"
              onClick={() => select({ kind: "utility", id: x.id })}
              className="flex w-full items-baseline justify-between gap-3 rounded py-0.5 text-left hover:text-[var(--blue)]"
            >
              <span>{x.name}</span>
              <span className="tabular-nums" style={{ color: "var(--ink-2)" }}>
                {n}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-5 text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
        Counts are of projects found in public reporting, not of capacity. Figures differ in kind
        (power agreements, plant output, floor area, investment), so they are not summed.
      </p>
      <label className="mt-4 block text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        Jump to a county
        <select
          value=""
          onChange={(e) => e.target.value && select({ kind: "county", id: e.target.value })}
          className="mt-1 block w-full rounded-md border px-2 py-1.5"
          style={{ borderColor: "var(--baseline)", background: "var(--surface-1)", color: "var(--ink-1)" }}
        >
          <option value="">Choose a county</option>
          {PA_COUNTIES.map((c) => (
            <option key={c.fips} value={c.fips}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mb-3 inline-flex items-center gap-1 rounded text-[0.85rem] font-medium hover:text-[var(--ink-1)]"
      style={{ color: "var(--ink-2)" }}
    >
      <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7.5 2 3.5 6l4 4" />
      </svg>
      All projects
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-2.5" style={{ background: "var(--surface-1)" }}>
      <dt style={{ color: "var(--ink-2)" }}>{label}</dt>
      <dd className="font-bold tabular-nums">{value}</dd>
    </div>
  );
}

function ProjectList({ dcs, select, showUtility = false }: { dcs: DataCenter[]; select: (s: Selection) => void; showUtility?: boolean }) {
  return (
    <ul className="flex flex-col">
      {dcs.map((dc) => (
        <li key={dc.id} className="border-t first:border-t-0" style={{ borderColor: "var(--border)" }}>
          <button
            type="button"
            onClick={() => select({ kind: "dc", id: dc.id })}
            className="block w-full py-2 text-left hover:text-[var(--blue)]"
          >
            <span className="block text-[0.9rem] font-semibold">
              {dc.name}
              {dc.ended ? (
                <span className="ml-2 rounded border px-1.5 py-px align-middle text-[0.68rem] font-semibold uppercase tracking-wide" style={{ borderColor: "var(--baseline)", color: "var(--ink-2)" }}>
                  Ended
                </span>
              ) : null}
            </span>
            <span className="block text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
              {dc.place}
              {showUtility && dc.utilityId ? `, ${utilityName(dc.utilityId)}` : ""}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function DcDetail({ dc, onBack, select }: { dc: DataCenter; onBack: () => void; select: (s: Selection) => void }) {
  const precision = {
    site: "Placed at or near the named site.",
    municipality: "Approximate: placed within the township, borough or city.",
  }[dc.precision];
  return (
    <div>
      <BackButton onClick={onBack} />
      <h3 className="mb-0.5 text-lg leading-snug font-bold">{dc.name}</h3>
      <p className="mb-3 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        {dc.place}
      </p>
      <p className="mb-3 text-[0.9rem]">{dc.summary}</p>
      <dl className="mb-4 grid grid-cols-1 gap-px overflow-hidden rounded-lg border text-[0.85rem]" style={{ background: "var(--border)", borderColor: "var(--border)" }}>
        {dc.figures.map((f) => (
          <div key={f.label} className="flex items-baseline justify-between gap-3 p-2.5" style={{ background: "var(--surface-1)" }}>
            <dt style={{ color: "var(--ink-2)" }}>
              {f.label}
              {f.note ? <span className="block text-[0.75rem]">{f.note}</span> : null}
            </dt>
            <dd className="text-right font-bold tabular-nums">{f.value}</dd>
          </div>
        ))}
      </dl>
      <h4 className="mb-1 text-sm font-bold">Status</h4>
      <p className="mb-1 text-[0.9rem]">{dc.status}</p>
      <p className="mb-4 text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
        As of: {dc.asOf}
      </p>
      <h4 className="mb-1 text-sm font-bold">Where it sits</h4>
      <p className="mb-4 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        {dc.county ? (
          <>
            <button type="button" className="underline underline-offset-2 hover:text-[var(--blue)]" onClick={() => select({ kind: "county", id: dc.countyFips! })}>
              {dc.county} County
            </button>
            {dc.utilityId ? (
              <>
                {", "}
                <button type="button" className="underline underline-offset-2 hover:text-[var(--blue)]" onClick={() => select({ kind: "utility", id: dc.utilityId! })}>
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
      <h4 className="mb-1.5 text-sm font-bold">Sources</h4>
      <div className="flex flex-wrap gap-1.5">
        {dc.sources.map((s) => (
          <SourceChip key={s.url} href={s.url} label={s.label} />
        ))}
      </div>
    </div>
  );
}
