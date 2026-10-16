"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  PA_COUNTIES,
  PA_UNITS_PER_MILE,
  PA_UTILITIES,
  PA_VIEWBOX,
  type PaUtility,
  type ZoneName,
} from "@/data/paGeo";
import { DATA_CENTERS, DATA_CENTERS_REVIEWED, type DataCenter, type StatusCategory } from "@/data/dataCenters";
import { POWER_PLANTS } from "@/data/powerPlants";
import { DcDetail } from "@/components/DcDetail";
import { ProjectTable } from "@/components/ProjectTable";
import { STATUS, STATUS_ORDER, StatusIcon, isStatus } from "@/components/mapStatus";
import { CloseIcon, ExpandIcon, MinusIcon, PlusIcon, ResetIcon } from "@/components/icons";

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
type Hover = { text: string; x: number; y: number } | null;

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

const RING_MILES = [1, 5];
const MIN_VIEW_W = 12; // closest zoom: about 3.6 miles across
const FULL_VB = { x: -PAD, y: -PAD, w: VB_W, h: VB_H };

type Box = { x: number; y: number; w: number; h: number };
type UserView = { w: number; cx: number; cy: number };

/** Widen or heighten a view box (about its center) until it matches the screen's aspect. */
function fitAspect(b: Box, ar: number): Box {
  let { w, h } = b;
  if (ar > w / h) w = h * ar;
  else h = w / ar;
  return { x: b.x + b.w / 2 - w / 2, y: b.y + b.h / 2 - h / 2, w, h };
}

function clampView(v: UserView): UserView {
  return {
    w: v.w,
    cx: Math.min(PA_VIEWBOX.w, Math.max(0, v.cx)),
    cy: Math.min(PA_VIEWBOX.h, Math.max(0, v.cy)),
  };
}
const ZOOM_WINDOW_MILES = 26; // map width shown while the rings are on

function fmtPrice(v: number | null) {
  if (v == null) return "n/a";
  return (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function utilityName(id: string | null) {
  return PA_UTILITIES.find((u) => u.id === id)?.name ?? "Other or unmapped utility";
}

function matchesQuery(d: DataCenter, q: string) {
  if (!q) return true;
  const hay = [d.name, d.developer, d.place, d.county ?? "", utilityName(d.utilityId), STATUS[d.statusCategory].label, d.status]
    .join(" ")
    .toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.includes(word));
}

/** One project's marker, drawn in screen-sized units. The shape is part of the meaning: it
 *  stays legible on any utility's tint and for readers who cannot tell the colors apart. */
function MarkerShape({ status, x, y, u }: { status: StatusCategory; x: number; y: number; u: number }) {
  const { shape, fill } = STATUS[status];
  const stroke = "var(--ink-1)";
  if (shape === "square") {
    return <rect x={x - 5.5 * u} y={y - 5.5 * u} width={11 * u} height={11 * u} fill={fill} stroke={stroke} strokeWidth={1.5 * u} />;
  }
  if (shape === "diamond") {
    const r = 7.5 * u;
    return <polygon points={`${x},${y - r} ${x + r},${y} ${x},${y + r} ${x - r},${y}`} fill={fill} stroke={stroke} strokeWidth={1.5 * u} />;
  }
  if (shape === "ring") {
    return <circle cx={x} cy={y} r={5 * u} fill="var(--surface-1)" stroke={stroke} strokeWidth={2.2 * u} />;
  }
  return <circle cx={x} cy={y} r={6 * u} fill={fill} stroke={stroke} strokeWidth={1.5 * u} />;
}

export function PaMap({ zoneStats }: { zoneStats?: Partial<Record<ZoneName, ZoneStat>> }) {
  const isPrivate = Boolean(zoneStats);
  const wrapRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const asideRef = useRef<HTMLElement>(null);
  const enlargeRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [width, setWidth] = useState(700);
  const [boxH, setBoxH] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [userView, setUserView] = useState<UserView | null>(null);
  const [placeholderH, setPlaceholderH] = useState(0);
  const [selection, setSelection] = useState<Selection>(null);
  const [hover, setHover] = useState<Hover>(null);
  const [showUtilities, setShowUtilities] = useState(true);
  const [showDc, setShowDc] = useState(true);
  const [showPlants, setShowPlants] = useState(false);
  const [rings, setRings] = useState(true);
  const [metric, setMetric] = useState<Metric>("none");
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<Set<StatusCategory>>(() => new Set(STATUS_ORDER));
  const [ready, setReady] = useState(false);
  const [copied, setCopied] = useState<"idle" | "ok" | "failed">("idle");

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setWidth(Math.max(280, rect.width));
      setBoxH(rect.height);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Shareable links: the selected project, status filters and search live in the address bar.
  // Read once on arrival (client only, so the server-rendered page is identical for everyone)...
  useEffect(() => {
    // Deferred a tick: the address bar is an external system, applied after hydration.
    queueMicrotask(() => {
      const params = new URLSearchParams(window.location.search);
      const project = params.get("project");
      if (project && DATA_CENTERS.some((d) => d.id === project)) setSelection({ kind: "dc", id: project });
      const statuses = (params.get("status") ?? "").split(",").filter(isStatus);
      if (statuses.length > 0) setActive(new Set(statuses));
      const q = params.get("q");
      if (q) setQuery(q.slice(0, 80));
      setReady(true);
    });
  }, []);

  // ...then keep the address bar in step with what is on screen.
  useEffect(() => {
    if (!ready) return;
    const params = new URLSearchParams();
    if (selection?.kind === "dc") params.set("project", selection.id);
    if (active.size !== STATUS_ORDER.length) params.set("status", STATUS_ORDER.filter((s) => active.has(s)).join(","));
    if (query.trim()) params.set("q", query.trim());
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [ready, selection, active, query]);

  const ringDc = selection?.kind === "dc" && rings ? DATA_CENTERS.find((d) => d.id === selection.id) : null;
  const showRings = Boolean(ringDc?.exposure);

  // With rings on, the map zooms to a window around the project, since a one-mile ring is a
  // few pixels wide at statewide scale. Everything else is sized in screen units via `u`.
  const autoVb = useMemo<Box>(() => {
    if (!showRings || !ringDc) return FULL_VB;
    const w = ZOOM_WINDOW_MILES * PA_UNITS_PER_MILE;
    const h = w * (VB_H / VB_W);
    return { x: ringDc.x - w / 2, y: ringDc.y - h / 2, w, h };
  }, [showRings, ringDc]);
  const zoomed = autoVb.w < VB_W;

  // Enlarged: the view matches the screen's shape, and the reader's own zoom and pan win.
  const aspect = expanded && boxH > 0 ? width / boxH : VB_W / VB_H;
  const vb = useMemo<Box>(() => {
    if (!expanded) return autoVb;
    if (!userView) return fitAspect(autoVb, aspect);
    const h = userView.w / aspect;
    return { x: userView.cx - userView.w / 2, y: userView.cy - h / 2, w: userView.w, h };
  }, [expanded, autoVb, userView, aspect]);
  const u = vb.w / width;

  const vbRef = useRef(vb);
  const aspectRef = useRef(aspect);
  useEffect(() => {
    vbRef.current = vb;
    aspectRef.current = aspect;
  });

  // Zoom about a point given as fractions of the map frame; factor above 1 zooms in.
  const zoomAt = useCallback((fx: number, fy: number, factor: number) => {
    const cur = vbRef.current;
    const ar = aspectRef.current;
    const maxW = fitAspect(FULL_VB, ar).w;
    const w = Math.min(maxW, Math.max(MIN_VIEW_W, cur.w / factor));
    const h = w / ar;
    const x = cur.x + fx * cur.w - fx * w;
    const y = cur.y + fy * cur.h - fy * h;
    vbRef.current = { x, y, w, h };
    setUserView(clampView({ w, cx: x + w / 2, cy: y + h / 2 }));
  }, []);

  const panBy = useCallback((dxUnits: number, dyUnits: number) => {
    const cur = vbRef.current;
    const x = cur.x - dxUnits;
    const y = cur.y - dyUnits;
    vbRef.current = { ...cur, x, y };
    setUserView(clampView({ w: cur.w, cx: x + cur.w / 2, cy: y + cur.h / 2 }));
  }, []);

  const openExpanded = () => {
    setPlaceholderH(wrapRef.current?.getBoundingClientRect().height ?? 0);
    setUserView(null);
    setExpanded(true);
  };
  const closeExpanded = useCallback(() => {
    setExpanded(false);
    setUserView(null);
    requestAnimationFrame(() => enlargeRef.current?.focus());
  }, []);

  // While enlarged: the page behind does not scroll, focus starts on Close, the wheel zooms
  // the map, and the keyboard can zoom, pan, reset and leave.
  useEffect(() => {
    if (!expanded) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const el = wrapRef.current;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el!.getBoundingClientRect();
      zoomAt((e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height, Math.exp(-e.deltaY * 0.0015));
    };
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const step = vbRef.current.w * 0.12;
      if (e.key === "Tab" && el) {
        const items = Array.from(el.querySelectorAll<HTMLElement>('button, select, [tabindex="0"]')).filter(
          (n) => !n.hasAttribute("disabled"),
        );
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
        return;
      }
      if (e.key === "Escape") closeExpanded();
      else if (e.key === "+" || e.key === "=") zoomAt(0.5, 0.5, 1.5);
      else if (e.key === "-" || e.key === "_") zoomAt(0.5, 0.5, 1 / 1.5);
      else if (e.key === "0") setUserView(null);
      else if (e.key === "ArrowLeft") panBy(step, 0);
      else if (e.key === "ArrowRight") panBy(-step, 0);
      else if (e.key === "ArrowUp") panBy(0, step);
      else if (e.key === "ArrowDown") panBy(0, -step);
      else return;
      e.preventDefault();
    };
    el?.addEventListener("wheel", onWheel, { passive: false });
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      el?.removeEventListener("wheel", onWheel);
      document.removeEventListener("keydown", onKey);
    };
  }, [expanded, zoomAt, panBy, closeExpanded]);

  // Drag to pan, two fingers to pinch. A drag must not also count as a click on what it started on.
  const pointers = useRef(new Map<number, { x: number; y: number; sx: number; sy: number }>());
  const gesture = useRef({ moved: false, lastDist: 0 });
  const onPointerDown = (e: React.PointerEvent) => {
    if (!expanded || (e.target as Element).closest("button, select, label")) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY });
    gesture.current = { moved: false, lastDist: 0 };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const p = pointers.current.get(e.pointerId);
    if (!expanded || !p) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const dx = e.clientX - p.x;
    const dy = e.clientY - p.y;
    p.x = e.clientX;
    p.y = e.clientY;
    if (!gesture.current.moved && Math.hypot(e.clientX - p.sx, e.clientY - p.sy) < 5) return;
    if (!gesture.current.moved) {
      gesture.current.moved = true;
      setHover(null);
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    if (pointers.current.size >= 2) {
      const [a, b] = Array.from(pointers.current.values());
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (gesture.current.lastDist > 0) {
        const mx = ((a.x + b.x) / 2 - rect.left) / rect.width;
        const my = ((a.y + b.y) / 2 - rect.top) / rect.height;
        zoomAt(mx, my, dist / gesture.current.lastDist);
      }
      gesture.current.lastDist = dist;
    } else {
      const perPx = vbRef.current.w / rect.width;
      panBy(dx * perPx, dy * perPx);
    }
  };
  const onPointerEnd = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    gesture.current.lastDist = 0;
  };

  const countsByStatus = useMemo(() => {
    const counts = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<StatusCategory, number>;
    for (const d of DATA_CENTERS) if (matchesQuery(d, query.trim())) counts[d.statusCategory] += 1;
    return counts;
  }, [query]);

  const selectedId = selection?.kind === "dc" ? selection.id : null;
  const visible = useMemo(
    () => DATA_CENTERS.filter((d) => active.has(d.statusCategory) && matchesQuery(d, query.trim())),
    [active, query],
  );
  // A project you are looking at stays on the map even if a filter would hide it.
  const shown = useMemo(() => {
    const chosen = selectedId ? DATA_CENTERS.find((d) => d.id === selectedId) : null;
    return chosen && !visible.includes(chosen) ? [...visible, chosen] : visible;
  }, [visible, selectedId]);
  const filtering = active.size !== STATUS_ORDER.length || query.trim() !== "";

  const countyByFips = useMemo(() => new Map(PA_COUNTIES.map((c) => [c.fips, c])), []);
  const selectedDc = selection?.kind === "dc" ? (DATA_CENTERS.find((d) => d.id === selection.id) ?? null) : null;
  const selectionLabel = !selection
    ? null
    : selection.kind === "dc"
      ? (selectedDc?.name ?? null)
      : selection.kind === "county"
        ? `${countyByFips.get(selection.id)?.name ?? ""} County`
        : (PA_UTILITIES.find((x) => x.id === selection.id)?.name ?? null);
  const dcByCounty = useMemo(() => {
    const m = new Map<string, DataCenter[]>();
    for (const dc of visible) {
      if (!dc.countyFips) continue;
      m.set(dc.countyFips, [...(m.get(dc.countyFips) ?? []), dc]);
    }
    return m;
  }, [visible]);

  // Private overlay: shade zone utilities by one metric, scaled to the max across the five zones.
  const metricValue = (x: PaUtility): number | null => {
    if (!zoneStats || !x.zone) return null;
    const s = zoneStats[x.zone];
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

  const select = (s: Selection) => {
    setUserView(null);
    setSelection((cur) => (cur && s && cur.kind === s.kind && cur.id === s.id ? null : s));
  };
  const pick = (id: string) => {
    setUserView(null);
    setSelection({ kind: "dc", id });
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    topRef.current?.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  };
  const toggleStatus = (s: StatusCategory) =>
    setActive((cur) => {
      const next = new Set(cur);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  const reset = () => {
    setActive(new Set(STATUS_ORDER));
    setQuery("");
  };
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
    setTimeout(() => setCopied("idle"), 2500);
  }

  return (
    <div>
      <div ref={topRef} className="scroll-mt-4" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Toggle pressed={showUtilities} onClick={() => setShowUtilities((v) => !v)} label="Utility territories" />
        <Toggle pressed={showDc} onClick={() => setShowDc((v) => !v)} label="Data center projects" />
        <Toggle pressed={showPlants} onClick={() => setShowPlants((v) => !v)} label="Power plants (100 MW+)" />
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

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="project-search">
          Search projects
        </label>
        <input
          id="project-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search name, place, developer"
          className="w-full rounded-md border px-3 py-2 text-[0.9rem] sm:w-72"
          style={{ borderColor: "var(--baseline)", background: "var(--surface-1)", color: "var(--ink-1)" }}
        />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by project status">
          {STATUS_ORDER.map((s) => {
            const on = active.has(s);
            return (
              <button
                key={s}
                type="button"
                aria-pressed={on}
                onClick={() => toggleStatus(s)}
                className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[0.8rem] font-medium transition-opacity"
                style={{
                  borderColor: on ? "var(--ink-1)" : "var(--baseline)",
                  background: "var(--surface-1)",
                  color: on ? "var(--ink-1)" : "var(--ink-2)",
                  opacity: on ? 1 : 0.6,
                }}
              >
                <StatusIcon status={s} size={11} />
                {STATUS[s].label}
                <span className="tabular-nums" style={{ color: "var(--ink-2)" }}>{countsByStatus[s]}</span>
              </button>
            );
          })}
          {filtering && (
            <button type="button" onClick={reset} className="rounded-full px-2.5 py-1 text-[0.8rem] font-medium underline underline-offset-2 hover:text-[var(--blue)]" style={{ color: "var(--ink-2)" }}>
              Reset
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="min-w-0">
          <div style={expanded ? { height: placeholderH } : undefined}>
          {expanded && (
            <div className="fixed inset-0 z-[45] bg-black/60" onClick={closeExpanded} aria-hidden="true" />
          )}
          <div
            ref={wrapRef}
            role={expanded ? "dialog" : undefined}
            aria-modal={expanded || undefined}
            aria-label={expanded ? "Enlarged map of Pennsylvania data center projects" : undefined}
            className={
              expanded
                ? "fixed inset-3 z-50 touch-none overflow-hidden rounded-[10px] border shadow-2xl"
                : "relative overflow-hidden rounded-[10px] border"
            }
            style={{ background: "var(--surface-1)", borderColor: "var(--border)", cursor: expanded ? "grab" : undefined }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerEnd}
            onPointerCancel={onPointerEnd}
            onClickCapture={(e) => {
              if (gesture.current.moved) {
                e.stopPropagation();
                gesture.current.moved = false;
              }
            }}
          >
            <svg
              viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
              className={expanded ? "block h-full w-full" : "block h-auto w-full"}
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
                  const hovered = hover?.text === `${c.name} County`;
                  return (
                    <path
                      key={c.fips}
                      d={c.d}
                      fill={hovered || selected ? "var(--ink-1)" : "transparent"}
                      fillOpacity={selected ? 0.12 : 0.07}
                      stroke={selected ? "var(--ink-1)" : "var(--baseline)"}
                      strokeWidth={(selected ? 1.8 : 0.8) * u}
                      strokeLinejoin="round"
                      style={{ cursor: "pointer" }}
                      onPointerEnter={() => setHover({ text: `${c.name} County`, x: c.cx, y: c.cy })}
                      onPointerLeave={() => setHover((cur) => (cur?.text === `${c.name} County` ? null : cur))}
                      onClick={() => select({ kind: "county", id: c.fips })}
                    />
                  );
                })}
              </g>

              {showPlants && (
                <g>
                  {POWER_PLANTS.map((p) => {
                    const label = `${p.name}: ${p.fuel}, ${p.mw.toLocaleString("en-US")} MW`;
                    const r = 5 * u;
                    return (
                      <polygon
                        key={`${p.name}-${p.x}`}
                        points={`${p.x},${p.y - r} ${p.x + r * 0.9},${p.y + r * 0.7} ${p.x - r * 0.9},${p.y + r * 0.7}`}
                        fill="var(--surface-1)"
                        stroke="var(--ink-2)"
                        strokeWidth={1.3 * u}
                        onPointerEnter={() => setHover({ text: label, x: p.x, y: p.y })}
                        onPointerLeave={() => setHover((cur) => (cur?.text === label ? null : cur))}
                      >
                        <title>{label}</title>
                      </polygon>
                    );
                  })}
                </g>
              )}

              {showRings && ringDc && (
                <g style={{ pointerEvents: "none" }}>
                  {RING_MILES.map((mi) => (
                    <g key={mi}>
                      <circle
                        cx={ringDc.x}
                        cy={ringDc.y}
                        r={mi * PA_UNITS_PER_MILE}
                        fill="var(--ink-1)"
                        fillOpacity={0.03}
                        stroke="var(--ink-1)"
                        strokeWidth={1.2 * u}
                        strokeDasharray={`${5 * u} ${4 * u}`}
                      />
                      <text
                        x={ringDc.x}
                        y={ringDc.y - mi * PA_UNITS_PER_MILE - 3 * u}
                        textAnchor="middle"
                        fontSize={11 * u}
                        fontWeight={600}
                        fill="var(--ink-1)"
                        stroke="var(--surface-1)"
                        strokeWidth={3 * u}
                        paintOrder="stroke"
                      >
                        {mi} mi
                      </text>
                    </g>
                  ))}
                </g>
              )}

              {showDc &&
                shown.map((dc) => {
                  const selected = selectedId === dc.id;
                  const hovered = hover?.text === dc.name;
                  return (
                    <g
                      key={dc.id}
                      role="button"
                      tabIndex={0}
                      aria-label={`${dc.name}, ${dc.place}, ${STATUS[dc.statusCategory].label}`}
                      aria-pressed={selected}
                      style={{ cursor: "pointer", outline: "none" }}
                      onPointerEnter={() => setHover({ text: dc.name, x: dc.x, y: dc.y })}
                      onPointerLeave={() => setHover((cur) => (cur?.text === dc.name ? null : cur))}
                      onFocus={() => setHover({ text: dc.name, x: dc.x, y: dc.y })}
                      onBlur={() => setHover((cur) => (cur?.text === dc.name ? null : cur))}
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
                      {(selected || hovered) && (
                        <circle cx={dc.x} cy={dc.y} r={12 * u} fill="none" stroke="var(--ink-1)" strokeWidth={1.5 * u} />
                      )}
                      <MarkerShape status={dc.statusCategory} x={dc.x} y={dc.y} u={u} />
                    </g>
                  );
                })}
            </svg>

            {hover && (
              <div
                className="pointer-events-none absolute z-10 rounded-md px-2 py-1 text-xs font-medium whitespace-nowrap shadow-md"
                style={{
                  background: "var(--ink-1)",
                  color: "var(--page)",
                  left: `${((hover.x - vb.x) / vb.w) * 100}%`,
                  top: `${((hover.y - vb.y) / vb.h) * 100}%`,
                  transform: `translate(${(hover.x - vb.x) / vb.w > 0.7 ? "-100%" : (hover.x - vb.x) / vb.w < 0.15 ? "0" : "-50%"}, calc(-100% - 14px))`,
                }}
              >
                {hover.text}
              </div>
            )}

            {!expanded && (
              <div className="absolute top-2 right-2 z-10">
                <MapButton label="Enlarge map" onClick={openExpanded} buttonRef={enlargeRef}>
                  <ExpandIcon />
                </MapButton>
              </div>
            )}

            {expanded && (
              <>
                <div className="absolute top-3 left-3 z-20 flex max-w-[calc(100%-11.5rem)] flex-wrap gap-2">
                  <Toggle pressed={showUtilities} onClick={() => setShowUtilities((v) => !v)} label="Territories" />
                  <Toggle pressed={showDc} onClick={() => setShowDc((v) => !v)} label="Projects" />
                  <Toggle pressed={showPlants} onClick={() => setShowPlants((v) => !v)} label="Plants" />
                </div>
                <div className="absolute top-3 right-3 z-20 flex items-center gap-1.5">
                  <MapButton label="Zoom out" onClick={() => zoomAt(0.5, 0.5, 1 / 1.6)}>
                    <MinusIcon />
                  </MapButton>
                  <MapButton label="Zoom in" onClick={() => zoomAt(0.5, 0.5, 1.6)}>
                    <PlusIcon />
                  </MapButton>
                  <MapButton label="Reset view" onClick={() => setUserView(null)}>
                    <ResetIcon />
                  </MapButton>
                  <MapButton label="Close enlarged map" onClick={closeExpanded} buttonRef={closeRef}>
                    <CloseIcon />
                  </MapButton>
                </div>
                <div className="absolute inset-x-3 bottom-3 z-20 flex flex-col items-start gap-2">
                  {selectionLabel && (
                    <div
                      className="flex max-w-full items-center gap-2.5 rounded-lg border py-1.5 pr-1.5 pl-3 text-[0.85rem]"
                      style={{ background: "var(--surface-1)", borderColor: "var(--baseline)" }}
                    >
                      {selectedDc && <StatusIcon status={selectedDc.statusCategory} />}
                      <span className="min-w-0 truncate font-semibold text-[var(--ink-1)]">{selectionLabel}</span>
                      <button
                        type="button"
                        onClick={() => {
                          closeExpanded();
                          requestAnimationFrame(() => asideRef.current?.scrollIntoView({ block: "start" }));
                        }}
                        className="shrink-0 rounded-md border px-2.5 py-1 text-[0.8rem] font-medium hover:border-[var(--ink-2)]"
                        style={{ borderColor: "var(--baseline)", color: "var(--ink-1)" }}
                      >
                        Details
                      </button>
                    </div>
                  )}
                  <div
                    className="flex max-w-full flex-wrap items-center gap-x-3.5 gap-y-1 rounded-lg border px-3 py-2 text-[0.75rem]"
                    style={{ background: "var(--surface-1)", borderColor: "var(--baseline)", color: "var(--ink-2)" }}
                  >
                    {STATUS_ORDER.map((st) => (
                      <span key={st} className="inline-flex items-center gap-1.5">
                        <StatusIcon status={st} size={11} />
                        {STATUS[st].label}
                      </span>
                    ))}
                    <span className="hidden sm:inline" style={{ color: "var(--ink-muted)" }}>
                      Scroll to zoom, drag to pan
                    </span>
                  </div>
                </div>
              </>
            )}
          </div>
          </div>

          {zoomed && !expanded && (
            <p className="mt-2 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
              Zoomed to the selected project.{" "}
              <button type="button" onClick={() => setRings(false)} className="underline underline-offset-2 hover:text-[var(--blue)]">
                Show the whole state
              </button>
            </p>
          )}

          <Legend
            isPrivate={isPrivate}
            metric={metric}
            metricMax={metricMax}
            selection={selection}
            showPlants={showPlants}
            showRings={showRings}
            onSelectUtility={(id) => select({ kind: "utility", id })}
          />
        </div>

        <aside
          ref={asideRef}
          className="min-w-0 scroll-mt-20 rounded-[10px] border p-5 lg:self-start"
          style={{ background: "var(--surface-1)", borderColor: "var(--border)" }}
          aria-live="polite"
        >
          <Panel
            selection={selection}
            setSelection={setSelection}
            select={select}
            pick={pick}
            visible={visible}
            dcByCounty={dcByCounty}
            countyByFips={countyByFips}
            zoneStats={zoneStats}
            rings={rings}
            setRings={setRings}
            filtering={filtering}
            copied={copied}
            onCopy={copyLink}
          />
        </aside>
      </div>

      <section className="mt-10" aria-labelledby="all-projects">
        <h2 id="all-projects" className="mb-1 text-xl font-bold">
          All projects
        </h2>
        <p className="mb-3 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
          Showing {visible.length} of {DATA_CENTERS.length}. Use the search and status filters above;
          select a column heading to sort.
        </p>
        <ProjectTable rows={visible} selectedId={selectedId} onSelect={pick} />
      </section>
    </div>
  );
}

function MapButton({
  label,
  onClick,
  children,
  buttonRef,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  buttonRef?: React.Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="grid size-9 place-items-center rounded-md border transition-colors hover:border-[var(--ink-2)] hover:text-[var(--ink-1)]"
      style={{ background: "var(--surface-1)", borderColor: "var(--baseline)", color: "var(--ink-2)" }}
    >
      {children}
    </button>
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
  showPlants,
  showRings,
  onSelectUtility,
}: {
  isPrivate: boolean;
  metric: Metric;
  metricMax: number;
  selection: Selection;
  showPlants: boolean;
  showRings: boolean;
  onSelectUtility: (id: string) => void;
}) {
  const zoneUtilities = PA_UTILITIES.filter((x) => UTILITY_COLOR[x.id]);
  const metricLabel: Record<Metric, string> = { none: "", current: "Current LMP", peak: "24h peak LMP", anomalies: "Anomalies (7d)" };
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
        {showPlants && (
          <span className="flex items-center gap-1.5">
            <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
              <polygon points="6,1 10.8,10 1.2,10" fill="var(--surface-1)" stroke="var(--ink-2)" strokeWidth="1.3" />
            </svg>
            Power plant, 100 MW or more
          </span>
        )}
        {showRings && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-full border border-dashed" style={{ borderColor: "var(--ink-1)" }} />
            1 and 5 miles from the marker
          </span>
        )}
      </div>
      {isPrivate && metric !== "none" && (
        <div className="mt-2 flex items-center gap-2 text-[0.8rem]">
          <span>{metricLabel[metric]}, low</span>
          <span
            className="h-2 w-28 rounded"
            style={{ background: "linear-gradient(to right, color-mix(in srgb, var(--blue) 12%, transparent), color-mix(in srgb, var(--blue) 80%, transparent))" }}
          />
          <span>high ({metric === "anomalies" ? Math.round(metricMax) : fmtPrice(metricMax)})</span>
        </div>
      )}
    </div>
  );
}

function Panel({
  selection,
  setSelection,
  select,
  pick,
  visible,
  dcByCounty,
  countyByFips,
  zoneStats,
  rings,
  setRings,
  filtering,
  copied,
  onCopy,
}: {
  selection: Selection;
  setSelection: (s: Selection) => void;
  select: (s: Selection) => void;
  pick: (id: string) => void;
  visible: DataCenter[];
  dcByCounty: Map<string, DataCenter[]>;
  countyByFips: Map<string, { name: string }>;
  zoneStats?: Partial<Record<ZoneName, ZoneStat>>;
  rings: boolean;
  setRings: (v: boolean) => void;
  filtering: boolean;
  copied: "idle" | "ok" | "failed";
  onCopy: () => void;
}) {
  const copyButton = (
    <button
      type="button"
      onClick={onCopy}
      className="mt-4 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[0.8rem] font-medium hover:border-[var(--blue)]"
      style={{ borderColor: "var(--baseline)", color: "var(--ink-2)" }}
    >
      {copied === "ok" ? "Link copied" : copied === "failed" ? "Copy failed: copy the address bar" : "Copy link to this view"}
    </button>
  );

  if (selection?.kind === "dc") {
    const dc = DATA_CENTERS.find((d) => d.id === selection.id);
    if (dc) {
      return (
        <div>
          <DcDetail
            dc={dc}
            rings={rings}
            onRings={setRings}
            onBack={() => setSelection(null)}
            onCounty={(fips) => select({ kind: "county", id: fips })}
            onUtility={(id) => select({ kind: "utility", id })}
          />
          {copyButton}
        </div>
      );
    }
  }

  if (selection?.kind === "county") {
    const dcs = dcByCounty.get(selection.id) ?? [];
    return (
      <div>
        <BackButton onClick={() => setSelection(null)} />
        <h3 className="mb-1 text-lg font-bold">{countyByFips.get(selection.id)?.name} County</h3>
        {dcs.length === 0 ? (
          <p className="text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
            No {filtering ? "matching " : ""}project in this county is tracked here. That does not
            mean none exist: this is a curated list from public reporting, not a complete registry.
          </p>
        ) : (
          <>
            <p className="mb-3 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
              {dcs.length} reported {dcs.length === 1 ? "project" : "projects"} in this county.
            </p>
            <ProjectList dcs={dcs} pick={pick} showUtility />
          </>
        )}
      </div>
    );
  }

  if (selection?.kind === "utility") {
    const x = PA_UTILITIES.find((v) => v.id === selection.id);
    if (!x) return null;
    const dcs = visible.filter((d) => d.utilityId === x.id);
    const zs = x.zone && zoneStats ? zoneStats[x.zone] : undefined;
    return (
      <div>
        <BackButton onClick={() => setSelection(null)} />
        <h3 className="mb-1 text-lg font-bold">{x.name}</h3>
        <p className="mb-3 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
          {x.holding}. About {x.customers.toLocaleString("en-US")} customers (HIFLD).
        </p>
        {zs && (
          <dl className="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border text-[0.85rem]" style={{ background: "var(--border)", borderColor: "var(--border)" }}>
            <Stat label="Current LMP" value={fmtPrice(zs.currentPrice)} />
            <Stat label="24h peak LMP" value={fmtPrice(zs.peak24hPrice)} />
            <Stat label="Anomalies (7d)" value={String(zs.anomalies7d)} />
            <Stat label="Freshness" value={zs.freshnessMinutes != null ? `${zs.freshnessMinutes}m` : "n/a"} />
          </dl>
        )}
        {x.id === "ppl" && (
          <p className="mb-4 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
            PPL reports an advanced-stage pipeline of 31.8 GW (Q2 2026). The projects below are
            individually reported sites, and this map does not attempt to reconcile them with that
            figure.
          </p>
        )}
        <h4 className="mb-2 text-sm font-bold">Reported projects in this territory</h4>
        {dcs.length === 0 ? (
          <p className="text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
            None {filtering ? "matching the filters" : "tracked here"}. This is not a complete registry.
          </p>
        ) : (
          <ProjectList dcs={dcs} pick={pick} />
        )}
      </div>
    );
  }

  // Default view
  const byUtility = PA_UTILITIES.map((x) => ({ x, n: visible.filter((d) => d.utilityId === x.id).length })).filter((r) => r.n > 0);
  const countiesShown = new Set(visible.map((d) => d.countyFips).filter(Boolean)).size;
  return (
    <div>
      <h3 className="mb-1 text-lg font-bold">
        {visible.length} {filtering ? `of ${DATA_CENTERS.length} ` : ""}reported {visible.length === 1 ? "project" : "projects"}
        {visible.length > 0 ? ` in ${countiesShown} ${countiesShown === 1 ? "county" : "counties"}` : ""}
      </h3>
      <p className="mb-3 text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        Select a project, county, or utility to see details. Reviewed {DATA_CENTERS_REVIEWED}.
      </p>
      {visible.length === 0 ? (
        <p className="text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
          No projects match the current search and filters.
        </p>
      ) : (
        <ProjectList dcs={visible} pick={pick} showUtility />
      )}
      {byUtility.length > 0 && (
        <>
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
                  <span className="tabular-nums" style={{ color: "var(--ink-2)" }}>{n}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
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
          {[...countyByFips.entries()]
            .sort((a, b) => a[1].name.localeCompare(b[1].name))
            .map(([fips, c]) => (
              <option key={fips} value={fips}>
                {c.name}
              </option>
            ))}
        </select>
      </label>
      {filtering && copyButton}
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
      <dd className="font-bold tabular-nums text-[var(--ink-1)]">{value}</dd>
    </div>
  );
}

function ProjectList({ dcs, pick, showUtility = false }: { dcs: DataCenter[]; pick: (id: string) => void; showUtility?: boolean }) {
  return (
    <ul className="flex flex-col">
      {dcs.map((dc) => (
        <li key={dc.id} className="border-t first:border-t-0" style={{ borderColor: "var(--border)" }}>
          <button type="button" onClick={() => pick(dc.id)} className="flex w-full items-start gap-2.5 py-2 text-left hover:text-[var(--blue)]">
            <span className="mt-1">
              <StatusIcon status={dc.statusCategory} />
            </span>
            <span>
              <span className="block text-[0.9rem] font-semibold text-[var(--ink-1)]">{dc.name}</span>
              <span className="block text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
                {STATUS[dc.statusCategory].label} &middot; {dc.place}
                {showUtility && dc.utilityId ? `, ${utilityName(dc.utilityId)}` : ""}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
