import type { StatusCategory } from "@/data/dataCenters";

// How a project's stage is shown. Each stage has its own SHAPE as well as a color, so the map
// never relies on color alone, and a marker reads the same on top of any utility's tint.
export const STATUS_ORDER: StatusCategory[] = [
  "announced",
  "review",
  "approved",
  "construction",
  "rejected",
  "abandoned",
];

type Shape = "circle" | "square" | "diamond" | "ring";

export const STATUS: Record<StatusCategory, { label: string; fill: string; shape: Shape }> = {
  announced: { label: "Announced", fill: "var(--ink-muted)", shape: "circle" },
  review: { label: "Under local review", fill: "var(--warning)", shape: "circle" },
  approved: { label: "Approved, first phase", fill: "var(--aqua)", shape: "circle" },
  construction: { label: "Under construction", fill: "var(--blue)", shape: "square" },
  rejected: { label: "Rejected locally", fill: "var(--red)", shape: "diamond" },
  abandoned: { label: "Abandoned", fill: "var(--surface-1)", shape: "ring" },
};

export function isStatus(value: string): value is StatusCategory {
  return (STATUS_ORDER as string[]).includes(value);
}

/** A small inline icon for lists, chips and the legend. */
export function StatusIcon({ status, size = 12 }: { status: StatusCategory; size?: number }) {
  const { shape, fill } = STATUS[status];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 12 12"
      aria-hidden="true"
      className="inline-block shrink-0"
    >
      {shape === "circle" && <circle cx="6" cy="6" r="4.6" fill={fill} stroke="var(--ink-1)" strokeWidth="1.2" />}
      {shape === "square" && <rect x="1.6" y="1.6" width="8.8" height="8.8" fill={fill} stroke="var(--ink-1)" strokeWidth="1.2" />}
      {shape === "diamond" && <polygon points="6,0.9 11.1,6 6,11.1 0.9,6" fill={fill} stroke="var(--ink-1)" strokeWidth="1.2" />}
      {shape === "ring" && <circle cx="6" cy="6" r="3.8" fill={fill} stroke="var(--ink-1)" strokeWidth="2" />}
    </svg>
  );
}
