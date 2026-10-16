"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { InfoIcon } from "@/components/icons";

/** A small info button that opens an explanation anchored above it. Meant to sit in the
 *  bottom-right corner of a `relative` card. Closes on Escape, on a click elsewhere, and
 *  leaves an enclosing dialog open when it consumes the Escape. */
export function InfoPopover({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault(); // keeps an enclosing <dialog> from also closing
      e.stopPropagation();
      setOpen(false);
    };
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="absolute right-3 bottom-3 z-20">
      {open && (
        <div
          id={panelId}
          role="note"
          className="absolute right-0 bottom-full mb-2 w-[min(27rem,calc(100vw-3rem))] rounded-lg border p-4 text-[0.85rem] leading-relaxed"
          style={{
            background: "var(--surface-1)",
            borderColor: "var(--baseline)",
            color: "var(--ink-body)",
            boxShadow: "0 6px 20px -4px rgb(0 0 0 / 0.28), 0 2px 6px rgb(0 0 0 / 0.12)",
          }}
        >
          {children}
        </div>
      )}
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="grid size-8 place-items-center rounded-full border transition-colors hover:text-[var(--ink-1)]"
        style={{
          background: "var(--surface-1)",
          borderColor: open ? "var(--ink-1)" : "var(--baseline)",
          color: open ? "var(--ink-1)" : "var(--ink-2)",
        }}
      >
        <InfoIcon />
      </button>
    </div>
  );
}
