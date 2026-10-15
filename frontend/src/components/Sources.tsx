import { SOURCES, type Source } from "@/lib/sources";

export function ExternalIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 12 12"
      width="10"
      height="10"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4.5 2.5H2.5a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2" />
      <path d="M7 1.5h3.5V5M10.5 1.5 5.5 6.5" />
    </svg>
  );
}

/** Numbered superscript pointing at the reference list at the foot of the page. */
export function Cite({ id, nums }: { id: string; nums: Record<string, number> }) {
  const s = SOURCES[id];
  const n = nums[id];
  if (!s || !n) return null;
  return (
    <sup className="ml-0.5 text-[0.72em] font-semibold leading-none">
      <a
        href={`#ref-${id}`}
        className="rounded px-0.5 no-underline hover:underline"
        style={{ color: "var(--ink-2)" }}
        aria-label={`Source ${n}: ${s.publisher}, ${s.title}`}
        title={`${s.publisher}: ${s.title}`}
      >
        [{n}]
      </a>
    </sup>
  );
}

/** Compact outbound link: publisher name plus an external-link mark. */
export function SourceChip({ id, href, label }: { id?: string; href?: string; label?: string }) {
  const s: Source | undefined = id ? SOURCES[id] : undefined;
  const url = href ?? s?.url;
  const text = label ?? s?.publisher;
  if (!url || !text) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={s ? s.title : undefined}
      className="inline-flex items-center gap-1 rounded-full border px-2 py-px align-baseline text-[0.8rem] font-medium no-underline transition-colors hover:border-[var(--blue)] hover:text-[var(--ink-1)]"
      style={{ borderColor: "var(--baseline)", color: "var(--ink-2)", background: "var(--surface-1)" }}
    >
      {text}
      <ExternalIcon className="opacity-70" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

/** Numbered reference list; each item is an anchor target for its superscript. */
export function ReferenceList({ ids, nums, heading = "Sources" }: { ids: string[]; nums: Record<string, number>; heading?: string }) {
  return (
    <section aria-labelledby="refs-heading">
      <h2 id="refs-heading" className="mb-3 text-xl font-bold">
        {heading}
      </h2>
      <ol className="flex flex-col text-[0.9rem]">
        {ids.map((id) => {
          const s = SOURCES[id];
          return (
            <li
              key={id}
              id={`ref-${id}`}
              className="grid scroll-mt-6 grid-cols-[2rem_1fr] gap-x-2 border-t py-3 first:border-t-0 target:bg-[color-mix(in_srgb,var(--blue)_10%,transparent)]"
              style={{ borderColor: "var(--border)" }}
            >
              <span className="pt-px text-[0.85rem] font-semibold tabular-nums" style={{ color: "var(--ink-2)" }}>
                {nums[id]}.
              </span>
              <div>
                <div className="mb-0.5 text-[0.72rem] font-bold uppercase tracking-wide" style={{ color: "var(--ink-2)" }}>
                  {s.kind}
                </div>
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="font-medium">
                  {s.publisher}: {s.title}
                  <ExternalIcon className="ml-1 inline-block align-baseline opacity-70" />
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
                <div className="mt-0.5" style={{ color: "var(--ink-2)" }}>
                  {s.note}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
