"use client";

import { useMemo, useState } from "react";
import { PA_UTILITIES } from "@/data/paGeo";
import type { DataCenter } from "@/data/dataCenters";
import { STATUS, STATUS_ORDER, StatusIcon } from "@/components/mapStatus";

type SortKey = "name" | "county" | "utility" | "status" | "people" | "asOf";

const utilityName = (id: string | null) => PA_UTILITIES.find((u) => u.id === id)?.name ?? "";
const peopleWithinOneMile = (d: DataCenter) => (d.exposure ? d.exposure.people[1] : null);

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "name", label: "Project" },
  { key: "county", label: "County" },
  { key: "utility", label: "Utility" },
  { key: "status", label: "Status" },
  { key: "people", label: "People within 1 mi", numeric: true },
  { key: "asOf", label: "As of" },
];

function sortValue(d: DataCenter, key: SortKey): string | number | null {
  switch (key) {
    case "name": return d.name.toLowerCase();
    case "county": return d.county ?? "";
    case "utility": return utilityName(d.utilityId).toLowerCase();
    case "status": return STATUS_ORDER.indexOf(d.statusCategory);
    case "people": return peopleWithinOneMile(d);
    case "asOf": return d.asOf.toLowerCase();
  }
}

/** The same projects as the map, in a sortable table. */
export function ProjectTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: DataCenter[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "name", dir: 1 });

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      const x = sortValue(a, sort.key);
      const y = sortValue(b, sort.key);
      if (x === y) return 0;
      if (x === null) return 1; // unmeasured rows sink to the bottom whichever way it sorts
      if (y === null) return -1;
      return (x < y ? -1 : 1) * sort.dir;
    });
  }, [rows, sort]);

  const toggle = (key: SortKey) =>
    setSort((cur) => (cur.key === key ? { key, dir: cur.dir === 1 ? -1 : 1 } : { key, dir: 1 }));

  return (
    <div className="overflow-x-auto rounded-[10px] border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
      <table className="w-full min-w-[720px] border-collapse text-[0.88rem]">
        <caption className="sr-only">Reported data center projects. Column headings sort the table.</caption>
        <thead>
          <tr>
            {COLUMNS.map((c) => {
              const active = sort.key === c.key;
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                  className={`border-b px-3.5 py-2.5 text-[0.75rem] font-semibold tracking-wide uppercase ${c.numeric ? "text-right" : "text-left"}`}
                  style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}
                >
                  <button type="button" onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 uppercase hover:text-[var(--ink-1)]">
                    {c.label}
                    <span aria-hidden="true" className={active ? "" : "opacity-30"}>
                      {active ? (sort.dir === 1 ? "▲" : "▼") : "▲"}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && (
            <tr>
              <td colSpan={COLUMNS.length} className="px-3.5 py-6 text-center" style={{ color: "var(--ink-2)" }}>
                No projects match the current search and filters.
              </td>
            </tr>
          )}
          {sorted.map((d) => (
            <tr
              key={d.id}
              className="border-b last:border-b-0"
              style={{
                borderColor: "var(--border)",
                background: d.id === selectedId ? "color-mix(in srgb, var(--blue) 9%, transparent)" : undefined,
              }}
            >
              <td className="px-3.5 py-2.5">
                <button type="button" onClick={() => onSelect(d.id)} className="text-left font-semibold text-[var(--ink-1)] underline decoration-[var(--baseline)] underline-offset-2 hover:decoration-[var(--blue)]">
                  {d.name}
                </button>
                <span className="block text-[0.78rem]" style={{ color: "var(--ink-2)" }}>{d.place}</span>
              </td>
              <td className="px-3.5 py-2.5">{d.county ?? ""}</td>
              <td className="px-3.5 py-2.5">{utilityName(d.utilityId)}</td>
              <td className="px-3.5 py-2.5 whitespace-nowrap">
                <span className="inline-flex items-center gap-1.5">
                  <StatusIcon status={d.statusCategory} />
                  {STATUS[d.statusCategory].label}
                </span>
              </td>
              <td className="px-3.5 py-2.5 text-right tabular-nums">
                {peopleWithinOneMile(d) === null ? (
                  <span style={{ color: "var(--ink-2)" }}>Not measured</span>
                ) : (
                  peopleWithinOneMile(d)!.toLocaleString("en-US")
                )}
              </td>
              <td className="px-3.5 py-2.5 text-[0.82rem]" style={{ color: "var(--ink-2)" }}>{d.asOf}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
