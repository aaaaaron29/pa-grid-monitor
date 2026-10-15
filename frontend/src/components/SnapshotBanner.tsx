import { REPO_URL, SNAPSHOT_LABEL, STATIC_DEMO } from "@/lib/staticDemo";

// Shown only on the static GitHub Pages snapshot. Says plainly what it is, since the numbers
// on it will not update.
export function SnapshotBanner() {
  if (!STATIC_DEMO) return null;
  return (
    <div
      role="note"
      className="border-b px-4 py-2 text-center text-[0.85rem]"
      style={{ background: "var(--surface-1)", borderColor: "var(--border)", color: "var(--ink-2)" }}
    >
      <b style={{ color: "var(--ink-1)" }}>Static demo.</b> A snapshot taken {SNAPSHOT_LABEL}. It does
      not update; the live site reads its database on every request.{" "}
      <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="font-medium">
        Source on GitHub
      </a>
    </div>
  );
}
