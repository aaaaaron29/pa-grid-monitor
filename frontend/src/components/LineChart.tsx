"use client";

import { useMemo, useRef, useState } from "react";

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

export interface LineChartProps<T extends Row> {
  data: T[];
  series: ChartSeries[];
  xKey?: string;
  xTickLabel?: (raw: unknown, index: number) => string;
  tooltipXLabel?: (raw: unknown, index: number) => string;
  flagKey?: string;
  yFormat?: (v: number) => string;
  annotations?: ChartAnnotation[];
  height?: number;
  xLabelEvery?: number;
}

const W = 700;

export function LineChart<T extends Row>({
  data,
  series,
  xKey = "t",
  xTickLabel,
  tooltipXLabel,
  flagKey,
  yFormat,
  annotations,
  height = 220,
  xLabelEvery = 1,
}: LineChartProps<T>) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const H = height;
  const padL = 50;
  const padR = 14;
  const padT = annotations?.length ? 30 : 12;
  const padB = 26;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const fmt = (n: number) => (yFormat ? yFormat(n) : Math.round(n).toLocaleString("en-US"));

  const { vMin, vMax } = useMemo(() => {
    const values: number[] = [];
    for (const d of data) {
      for (const s of series) {
        const v = d[s.key];
        if (typeof v === "number") values.push(v);
      }
    }
    let min = Math.min(...values);
    let max = Math.max(...values);
    const pad = (max - min) * 0.08 || 1;
    min -= pad;
    max += pad;
    return { vMin: min, vMax: max };
  }, [data, series]);

  if (data.length === 0) {
    return (
      <div className="flex h-[220px] items-center justify-center text-sm" style={{ color: "var(--ink-muted)" }}>
        No data yet.
      </div>
    );
  }

  const x = (i: number) => padL + (i / Math.max(data.length - 1, 1)) * plotW;
  const y = (v: number) => padT + plotH - ((v - vMin) / (vMax - vMin || 1)) * plotH;

  const linePath = (key: string) =>
    data
      .map((d, i) => {
        const v = d[key];
        if (typeof v !== "number") return null;
        return `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(v).toFixed(2)}`;
      })
      .filter(Boolean)
      .join(" ");

  function handleMove(evt: React.PointerEvent<SVGRectElement>) {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const px = ((evt.clientX - rect.left) / rect.width) * W;
    let i = Math.round(((px - padL) / plotW) * (data.length - 1));
    i = Math.max(0, Math.min(data.length - 1, i));
    setHoverIndex(i);
  }

  const hovered = hoverIndex !== null ? data[hoverIndex] : null;
  const steps = 4;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="block w-full"
        style={{ overflow: "visible" }}
      >
        {Array.from({ length: steps + 1 }).map((_, s) => {
          const v = vMin + ((vMax - vMin) * s) / steps;
          const yy = y(v);
          return (
            <g key={s}>
              <line x1={padL} x2={W - padR} y1={yy} y2={yy} stroke="var(--grid)" strokeWidth={1} />
              <text x={padL - 8} y={yy + 3} textAnchor="end" fontSize={10} fill="var(--ink-muted)">
                {fmt(v)}
              </text>
            </g>
          );
        })}

        {data.map((d, i) => {
          if (i % xLabelEvery !== 0 && i !== data.length - 1) return null;
          const raw = d[xKey];
          const label = xTickLabel ? xTickLabel(raw, i) : String(raw ?? "").slice(5, 10);
          return (
            <text
              key={i}
              x={x(i)}
              y={H - 6}
              textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}
              fontSize={10}
              fill="var(--ink-muted)"
            >
              {label}
            </text>
          );
        })}

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
              <circle cx={ax} cy={14} r={8} fill="var(--surface-1)" stroke="var(--orange)" strokeWidth={1.5} />
              <text x={ax} y={18} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--orange)">
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
          onPointerLeave={() => setHoverIndex(null)}
        />
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute z-10 rounded-md px-2 py-1 text-xs"
          style={{
            background: "var(--ink-1)",
            color: "var(--page)",
            left: `${(x(hoverIndex!) / W) * 100}%`,
            top: `${(padT / H) * 100}%`,
            transform: "translate(-50%, -115%)",
          }}
        >
          <div>{tooltipXLabel ? tooltipXLabel(hovered[xKey], hoverIndex!) : String(hovered[xKey])}</div>
          {series.map((s) => {
            const v = hovered[s.key];
            return (
              <div key={s.key}>
                {s.label}: {typeof v === "number" ? fmt(v) : "--"}
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
    <div className="mt-2.5 flex flex-wrap gap-4 text-xs" style={{ color: "var(--ink-2)" }}>
      {series.map((s) => (
        <div key={s.key} className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3.5 rounded" style={{ background: s.color }} />
          {s.label}
        </div>
      ))}
    </div>
  );
}
