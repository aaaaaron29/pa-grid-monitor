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
    <section
      className="min-w-0 rounded-[10px] border p-5"
      style={{ background: "var(--surface-1)", borderColor: "var(--border)" }}
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className="text-[0.95rem] font-bold">{title}</h2>
        <div className="text-[0.78rem]" style={{ color: "var(--ink-2)" }}>
          {meta}
        </div>
      </div>
      {children}
      {legend}
      {footnote && (
        <p className="mt-3 text-[0.78rem]" style={{ color: "var(--ink-2)" }}>
          {footnote}
        </p>
      )}
    </section>
  );
}

const COLS: Record<number, string> = {
  3: "grid-cols-1 sm:grid-cols-3",
  4: "grid-cols-2 md:grid-cols-4",
};

export function StatsGrid({ children, cols = 4 }: { children: ReactNode; cols?: 3 | 4 }) {
  return (
    <div
      className={`grid ${COLS[cols]} gap-px overflow-hidden rounded-[10px] border`}
      style={{ background: "var(--border)", borderColor: "var(--border)" }}
    >
      {children}
    </div>
  );
}

export function StatTile({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="min-w-0 p-4" style={{ background: "var(--surface-1)" }}>
      <div className="mb-1.5 text-[0.78rem]" style={{ color: "var(--ink-2)" }}>
        {label}
      </div>
      <div className="text-[1.45rem] leading-tight font-bold tabular-nums text-[var(--ink-1)]">{value}</div>
      {sub && (
        <div className="mt-1 text-[0.78rem]" style={{ color: "var(--ink-2)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}
