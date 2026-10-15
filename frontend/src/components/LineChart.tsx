"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export interface ChartSeries {
  key: string;
  color: string;
  label: string;
}

export interface ChartAnnotation {
  index: number;
  label: string;
}

type Row = Record<string, unknown>;

// LineChart is a Client Component, so its props must be serializable: server pages cannot
// hand it formatter functions. Formatting is chosen by name instead.
export type XKind = "datetime" | "month";
export type YFormat = "number" | "usd";

export interface LineChartProps<T extends Row> {
  data: T[];
  series: ChartSeries[];
  xKey?: string;
  /** "datetime": ISO timestamps (tick "MM-DD", tooltip "MM-DD HH:MM"). "month": "YYYY-MM" as-is. */
  xKind?: XKind;
  flagKey?: string;
  /** "number": rounded with thousands separators. "usd": two-decimal dollars. */
  yFormat?: YFormat;
  annotations?: ChartAnnotation[];
  height?: number;
  /** Month charts only: label every Nth point. Defaults to a spacing that fits the width. */
  xLabelEvery?: number;
  emptyMessage?: string;
}

function formatY(kind: YFormat, v: number) {
  if (kind === "usd") {
    const sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return Math.round(v).toLocaleString("en-US");
}

function tickLabel(kind: XKind, raw: unknown) {
  const s = String(raw ?? "");
  return kind === "month" ? s : s.slice(5, 10);
}

function tooltipLabel(kind: XKind, raw: unknown) {
  const s = String(raw ?? "");
  return kind === "month" ? s : s.slice(5, 16).replace("T", " ");
}

const DEFAULT_W = 700;
const MIN_TICK_GAP = 56;

export function LineChart<T extends Row>({
  data,
  series,
  xKey = "t",
  xKind = "datetime",
  flagKey,
  yFormat = "number",
  annotations,
  height = 220,
  xLabelEvery,
  emptyMessage = "No data yet.",
}: LineChartProps<T>) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(DEFAULT_W);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  // Draw in real pixels so text and markers keep their proportions at every card width.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setW(Math.max(260, Math.round(el.getBoundingClientRect().width)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const H = height;
  const padL = 58;
  const padR = 14;
  const padT = annotations?.length ? 34 : 12;
  const padB = 28;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const fmt = (n: number) => formatY(yFormat, n);

  const { vMin, vMax } = useMemo(() => {
    const values: number[] = [];
    for (const d of data) {
      for (const s of series) {
        const v = d[s.key];
        if (typeof v === "number") values.push(v);
      }
    }
    if (values.length === 0) return { vMin: 0, vMax: 1 };
    let min = Math.min(...values);
    let max = Math.max(...values);
    const pad = (max - min) * 0.08 || 1;
    min -= pad;
    max += pad;
    return { vMin: min, vMax: max };
  }, [data, series]);

  const x = (i: number) => padL + (i / Math.max(data.length - 1, 1)) * plotW;
  const y = (v: number) => padT + plotH - ((v - vMin) / (vMax - vMin || 1)) * plotH;

  // Which points get an x label: day starts for timestamps, every Nth for months, then
  // thinned so neighbours never collide.
  const tickIndices = useMemo(() => {
    const candidates: number[] = [];
    if (xKind === "datetime") {
      for (let i = 0; i < data.length; i++) {
        const cur = String(data[i][xKey] ?? "").slice(0, 10);
        const prev = i > 0 ? String(data[i - 1][xKey] ?? "").slice(0, 10) : "";
        // A partial first day is skipped: its label would crowd the first real day boundary.
        const isDayStart = i > 0 ? cur !== prev : String(data[i][xKey] ?? "").slice(11, 13) === "00";
        if (isDayStart) candidates.push(i);
      }
    } else {
      const every = xLabelEvery ?? Math.max(1, Math.ceil(data.length / Math.floor(plotW / 90)));
      for (let i = 0; i < data.length; i += every) candidates.push(i);
    }
    const kept: number[] = [];
    let lastX = -Infinity;
    for (const i of candidates) {
      const px = padL + (i / Math.max(data.length - 1, 1)) * plotW;
      if (px - lastX >= MIN_TICK_GAP) {
        kept.push(i);
        lastX = px;
      }
    }
    return kept;
  }, [data, xKey, xKind, xLabelEvery, plotW]);

  // A new subpath starts after every gap, so a null value never leaves a path beginning with "L".
  const linePath = (key: string) => {
    let pen = false;
    let out = "";
    data.forEach((d, i) => {
      const v = d[key];
      if (typeof v !== "number") {
        pen = false;
        return;
      }
      out += `${pen ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)} `;
      pen = true;
    });
    return out.trim();
  };

  function handleMove(evt: React.PointerEvent<SVGRectElement>) {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = evt.clientX - rect.left;
    let i = Math.round(((px - padL) / plotW) * (data.length - 1));
    i = Math.max(0, Math.min(data.length - 1, i));
    setHoverIndex(i);
  }

  const hovered = hoverIndex !== null ? data[hoverIndex] : null;
  const steps = 4;
  const label = `Line chart of ${series.map((s) => s.label).join(" and ")}`;

  return (
    <div ref={wrapRef} className="relative w-full min-w-0" style={{ minHeight: H }}>
      {data.length === 0 ? (
        <div className="flex items-center justify-center text-sm" style={{ height: H, color: "var(--ink-2)" }}>
          {emptyMessage}
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          height={H}
          role="img"
          aria-label={label}
          className="block w-full touch-pan-y"
          style={{ overflow: "visible" }}
        >
          {Array.from({ length: steps + 1 }).map((_, s) => {
            const v = vMin + ((vMax - vMin) * s) / steps;
            const yy = y(v);
            return (
              <g key={s}>
                <line x1={padL} x2={W - padR} y1={yy} y2={yy} stroke="var(--grid)" strokeWidth={1} />
                <text x={padL - 8} y={yy + 3.5} textAnchor="end" fontSize={11} fill="var(--ink-2)" className="tabular-nums">
                  {fmt(v)}
                </text>
              </g>
            );
          })}

          {tickIndices.map((i) => (
            <text
              key={i}
              x={x(i)}
              y={H - 8}
              textAnchor={i === 0 ? "start" : "middle"}
              fontSize={11}
              fill="var(--ink-2)"
            >
              {tickLabel(xKind, data[i][xKey])}
            </text>
          ))}

          {series.map((s) => (
            <path
              key={s.key}
              d={linePath(s.key)}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}

          {flagKey &&
            data.map((d, i) => {
              if (!d[flagKey]) return null;
              const v = d[series[0].key];
              if (typeof v !== "number") return null;
              return (
                <circle
                  key={i}
                  cx={x(i)}
                  cy={y(v)}
                  r={4.5}
                  fill="var(--red)"
                  stroke="var(--surface-1)"
                  strokeWidth={1.5}
                />
              );
            })}

          {(() => {
            const lastV = data[data.length - 1][series[0].key];
            if (typeof lastV !== "number") return null;
            return <circle cx={x(data.length - 1)} cy={y(lastV)} r={3} fill={series[0].color} />;
          })()}

          {annotations?.map((a) => {
            const ax = x(a.index);
            return (
              <g key={a.index}>
                <line x1={ax} x2={ax} y1={padT} y2={padT + plotH} stroke="var(--baseline)" strokeWidth={1} strokeDasharray="3,3" />
                <circle cx={ax} cy={15} r={9} fill="var(--surface-1)" stroke="var(--orange)" strokeWidth={1.5} />
                <text x={ax} y={19} textAnchor="middle" fontSize={11} fontWeight={700} fill="var(--ink-1)">
                  {a.label}
                </text>
              </g>
            );
          })}

          {hoverIndex !== null && (
            <g>
              <line x1={x(hoverIndex)} x2={x(hoverIndex)} y1={padT} y2={padT + plotH} stroke="var(--baseline)" strokeWidth={1} />
              {series.map((s) => {
                const v = data[hoverIndex][s.key];
                if (typeof v !== "number") return null;
                return (
                  <circle key={s.key} cx={x(hoverIndex)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface-1)" strokeWidth={1.5} />
                );
              })}
            </g>
          )}

          <rect
            x={padL}
            y={padT}
            width={plotW}
            height={plotH}
            fill="transparent"
            onPointerMove={handleMove}
            onPointerDown={handleMove}
            onPointerLeave={() => setHoverIndex(null)}
          />
        </svg>
      )}

      {hovered && hoverIndex !== null && (
        <div
          className="pointer-events-none absolute z-10 rounded-md px-2.5 py-1.5 text-xs tabular-nums shadow-md"
          style={{
            background: "var(--ink-1)",
            color: "var(--page)",
            left: x(hoverIndex) + (x(hoverIndex) > W / 2 ? -12 : 12),
            top: padT + 6,
            transform: x(hoverIndex) > W / 2 ? "translateX(-100%)" : "none",
            whiteSpace: "nowrap",
          }}
        >
          <div className="font-semibold">{tooltipLabel(xKind, hovered[xKey])}</div>
          {series.map((s) => {
            const v = hovered[s.key];
            return (
              <div key={s.key}>
                {s.label}: {typeof v === "number" ? fmt(v) : "n/a"}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ChartLegend({ series }: { series: ChartSeries[] }) {
  return (
    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ color: "var(--ink-2)" }}>
      {series.map((s) => (
        <div key={s.key} className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3.5 rounded" style={{ background: s.color }} />
          {s.label}
        </div>
      ))}
    </div>
  );
}
