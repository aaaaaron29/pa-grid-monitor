"use client";

import { useEffect, useRef, useState } from "react";

export type RailItem = { id: string; label: string };

// A section counts as reached once its top passes this many px below the viewport top. Anchors
// land at 72px (scroll-padding-top in globals.css), so this must stay a little below that: a jump
// to a short section then leaves that section current instead of handing over to the next.
const readingLine = () => 140;
// Vertical centre of each marker inside its list row, in px.
const DOT_CENTER = 13;

// The rail lives in the blank margin left of the page content, so how wide a page is decides
// when there is room for it. The class strings are written out whole so Tailwind can see them.
const LAYOUTS = {
  /** Reading pages (680px column). */
  narrow: {
    rail: "hidden min-[1080px]:block w-[calc(50%-340px)]",
    pill: "min-[1080px]:hidden",
  },
  /** Tool pages (1100px column). */
  wide: {
    rail: "hidden min-[1500px]:block w-[calc(50%-550px)]",
    pill: "min-[1500px]:hidden",
  },
} as const;

/**
 * "On this page": a list of the page's sections, pinned in the left margin. The marker and the
 * line beside it fill as you scroll, the current section is emphasised, and each entry jumps
 * to its section. Where the margin is too narrow it becomes a small pill, bottom-left, that
 * opens the same list.
 */
export function SectionRail({ items, width }: { items: RailItem[]; width: keyof typeof LAYOUTS }) {
  const [active, setActive] = useState(0);
  const activeRef = useRef(0);
  const rowRefs = useRef<(HTMLLIElement | null)[]>([]);
  const fillRef = useRef<HTMLSpanElement>(null);
  const lockRef = useRef(false);
  const lockTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let frame = 0;

    function update() {
      frame = 0;
      const line = readingLine();
      const tops = items.map((it) => document.getElementById(it.id)?.getBoundingClientRect().top ?? NaN);
      const present = tops.map((t, i) => (Number.isNaN(t) ? -1 : i)).filter((i) => i >= 0);
      if (present.length === 0) return;

      let idx = present[0];
      for (const i of present) if (tops[i] <= line) idx = i;
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      if (atBottom) idx = present[present.length - 1];

      // Fill the line to a point between this marker and the next, by how far through the
      // section the reading line has travelled.
      const dotY = (i: number) => (rowRefs.current[i]?.offsetTop ?? 0) + DOT_CENTER;
      const next = present[present.indexOf(idx) + 1];
      let fillTo = dotY(idx);
      if (next !== undefined && !atBottom) {
        const span = tops[next] - tops[idx];
        const frac = span > 0 ? Math.min(1, Math.max(0, (line - tops[idx]) / span)) : 0;
        fillTo += frac * (dotY(next) - dotY(idx));
      }
      if (fillRef.current) fillRef.current.style.height = `${Math.max(0, fillTo)}px`;

      if (!lockRef.current && idx !== activeRef.current) {
        activeRef.current = idx;
        setActive(idx);
      }
    }

    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    const unlock = () => {
      lockRef.current = false;
      schedule();
    };

    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    window.addEventListener("scrollend", unlock);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      clearTimeout(lockTimer.current);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scrollend", unlock);
    };
  }, [items]);

  // A click scrolls smoothly past the sections in between; hold the highlight on the target
  // instead of letting it step through each one on the way.
  function onJump(index: number) {
    lockRef.current = true;
    activeRef.current = index;
    setActive(index);
    clearTimeout(lockTimer.current);
    lockTimer.current = setTimeout(() => {
      lockRef.current = false;
    }, 1200);
  }

  const layout = LAYOUTS[width];

  return (
    <>
      <div className={`fixed top-24 left-0 z-30 max-h-[calc(100vh-8rem)] overflow-y-auto print:hidden ${layout.rail}`}>
        <nav aria-label="On this page" className="ml-auto max-w-[14rem] pr-4 pl-3">
          <div
            className="mb-2.5 pl-5 text-[0.7rem] font-bold tracking-[0.08em] uppercase"
            style={{ color: "var(--ink-2)" }}
          >
            On this page
          </div>
          <ol className="relative">
            <span
              aria-hidden="true"
              className="absolute top-0 bottom-0 left-[4px] w-px"
              style={{ background: "var(--border)" }}
            />
            <span
              ref={fillRef}
              aria-hidden="true"
              className="absolute top-0 left-[4px] w-px"
              style={{ background: "var(--blue)", height: 0 }}
            />
            {items.map((it, i) => {
              const state = i < active ? "past" : i === active ? "current" : "ahead";
              return (
                <li key={it.id} ref={(el) => void (rowRefs.current[i] = el)} className="relative">
                  <a
                    href={`#${it.id}`}
                    onClick={() => onJump(i)}
                    aria-current={state === "current" ? "location" : undefined}
                    className="block py-1 pl-5 text-[0.82rem] leading-snug no-underline underline-offset-4 hover:text-[var(--ink-1)] hover:underline"
                    style={{
                      color: state === "current" ? "var(--ink-1)" : "var(--ink-2)",
                      fontWeight: state === "current" ? 650 : 400,
                      textDecorationColor: "var(--blue)",
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="absolute rounded-full border transition-[width,height,top,left,background-color] duration-200"
                      style={{
                        // 9px normally, 13px when current; both centred on x=4.5, y=DOT_CENTER.
                        width: state === "current" ? 13 : 9,
                        height: state === "current" ? 13 : 9,
                        left: state === "current" ? -2 : 0,
                        top: DOT_CENTER - (state === "current" ? 6.5 : 4.5),
                        background: state === "ahead" ? "var(--page)" : "var(--blue)",
                        borderColor: state === "ahead" ? "var(--baseline)" : "var(--blue)",
                        boxShadow:
                          state === "current" ? "0 0 0 3px color-mix(in srgb, var(--blue) 22%, transparent)" : "none",
                      }}
                    />
                    {it.label}
                  </a>
                </li>
              );
            })}
          </ol>
        </nav>
      </div>

      <JumpPill items={items} current={items[active]?.label ?? ""} className={layout.pill} onJump={onJump} />
    </>
  );
}

/** The narrow-screen form: a pill showing the current section that opens the list upward. */
function JumpPill({
  items,
  current,
  className,
  onJump,
}: {
  items: RailItem[];
  current: string;
  className: string;
  onJump: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={`fixed bottom-4 left-4 z-30 print:hidden ${className}`}>
      {open && (
        <ol
          className="absolute bottom-full left-0 mb-2 w-[min(18rem,calc(100vw-2rem))] rounded-lg border py-1.5 text-[0.88rem]"
          style={{
            background: "var(--surface-1)",
            borderColor: "var(--baseline)",
            boxShadow: "0 6px 20px -4px rgb(0 0 0 / 0.28), 0 2px 6px rgb(0 0 0 / 0.12)",
          }}
        >
          {items.map((it, i) => (
            <li key={it.id}>
              <a
                href={`#${it.id}`}
                onClick={() => {
                  onJump(i);
                  setOpen(false);
                }}
                className="block px-3.5 py-2 no-underline hover:bg-[color-mix(in_srgb,var(--blue)_10%,transparent)]"
                style={{
                  color: it.label === current ? "var(--ink-1)" : "var(--ink-2)",
                  fontWeight: it.label === current ? 650 : 400,
                }}
              >
                {it.label}
              </a>
            </li>
          ))}
        </ol>
      )}
      <button
        type="button"
        aria-expanded={open}
        aria-label="Jump to a section"
        onClick={() => setOpen((v) => !v)}
        className="flex max-w-[16rem] items-center gap-2 rounded-full border py-1.5 pr-3.5 pl-3 text-[0.8rem] font-semibold"
        style={{
          background: "var(--surface-1)",
          borderColor: open ? "var(--ink-1)" : "var(--baseline)",
          color: "var(--ink-1)",
          boxShadow: "0 2px 8px rgb(0 0 0 / 0.18)",
        }}
      >
        <span aria-hidden="true" className="size-2 shrink-0 rounded-full" style={{ background: "var(--blue)" }} />
        <span className="truncate">{current}</span>
      </button>
    </div>
  );
}
