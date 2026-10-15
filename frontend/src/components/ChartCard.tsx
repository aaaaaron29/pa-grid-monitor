import type { ReactNode } from "react";

export function ChartCard({
  title,
  meta,
  children,
  legend,
  footnote,
}: {
  title: string;
  meta: string;
  children: ReactNode;
  legend?: ReactNode;
  footnote?: ReactNode;
}) {
  return (
    <div
      className="rounded-[10px] border p-5"
      style={{ background: "var(--surface-1)", borderColor: "var(--border)" }}
    >
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-3">
        <div className="text-[0.95rem] font-bold">{title}</div>
        <div className="text-[0.78rem]" style={{ color: "var(--ink-muted)" }}>
          {meta}
        </div>
      </div>
      {children}
      {legend}
      {footnote && (
        <p className="mt-2.5 text-[0.78rem]" style={{ color: "var(--ink-muted)" }}>
          {footnote}
        </p>
      )}
    </div>
  );
}

export function StatsGrid({ children, cols = 4 }: { children: ReactNode; cols?: number }) {
  return (
    <div
      className="grid gap-px overflow-hidden rounded-[10px] border"
      style={{
        background: "var(--border)",
        borderColor: "var(--border)",
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
      }}
    >
      {children}
    </div>
  );
}

export function StatTile({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="min-w-0 p-4" style={{ background: "var(--surface-1)" }}>
      <div className="mb-1.5 text-[0.75rem]" style={{ color: "var(--ink-muted)" }}>
        {label}
      </div>
      <div className="text-2xl font-bold tabular-nums">{value}</div>
      {sub && (
        <div className="mt-0.5 text-[0.78rem]" style={{ color: "var(--ink-muted)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}
