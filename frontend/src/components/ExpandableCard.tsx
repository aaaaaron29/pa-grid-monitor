"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { CloseIcon, ExpandIcon } from "@/components/icons";
import { InfoPopover } from "@/components/InfoPopover";

interface Props {
  title: string;
  meta: string;
  /** The chart as shown in the card. */
  children: ReactNode;
  /** The same chart sized to fill the enlarged view. Rendered only while it is open. */
  expanded?: ReactNode;
  legend?: ReactNode;
  footnote?: ReactNode;
  /** Explanation shown by the info button in the card's bottom-right corner. */
  info?: ReactNode;
  infoLabel?: string;
}

const BUTTON =
  "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[0.78rem] font-medium transition-colors hover:text-[var(--ink-1)] hover:border-[var(--ink-2)]";

export function ExpandableCard({ title, meta, children, expanded, legend, footnote, info, infoLabel }: Props) {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && dialog && !dialog.open) dialog.showModal();
  }, [open]);

  // The page behind should not scroll while the enlarged view is up.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  const reserve = info ? "pr-11" : "";

  return (
    <section
      className="relative min-w-0 rounded-[10px] border p-5"
      style={{ background: "var(--surface-1)", borderColor: "var(--border)" }}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-[0.95rem] font-bold">{title}</h2>
        <div className="flex items-center gap-3">
          <div className="text-[0.78rem]" style={{ color: "var(--ink-2)" }}>
            {meta}
          </div>
          {expanded && (
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label={`Enlarge chart: ${title}`}
              className={BUTTON}
              style={{ borderColor: "var(--baseline)", color: "var(--ink-2)" }}
            >
              <ExpandIcon />
              Enlarge
            </button>
          )}
        </div>
      </div>
      {children}
      <div className={reserve}>{legend}</div>
      {footnote && (
        <p className={`mt-3 text-[0.78rem] ${reserve}`} style={{ color: "var(--ink-2)" }}>
          {footnote}
        </p>
      )}
      {info && <InfoPopover label={infoLabel ?? "About this chart"}>{info}</InfoPopover>}

      {expanded && (
        <dialog
          ref={dialogRef}
          aria-label={title}
          onClose={() => setOpen(false)}
          onClick={(e) => {
            if (e.target === e.currentTarget) e.currentTarget.close();
          }}
          className="m-auto h-[calc(100dvh-1.5rem)] max-h-none w-[calc(100vw-1.5rem)] max-w-none overflow-hidden rounded-[10px] border p-0 backdrop:bg-black/60"
          style={{ background: "var(--surface-1)", borderColor: "var(--border)", color: "var(--ink-body)" }}
        >
          {open && (
            <div className="relative flex h-full flex-col p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-3">
                  <h2 className="text-lg font-bold">{title}</h2>
                  <div className="text-[0.82rem]" style={{ color: "var(--ink-2)" }}>
                    {meta}
                  </div>
                </div>
                <button
                  type="button"
                  autoFocus
                  onClick={() => dialogRef.current?.close()}
                  className={BUTTON}
                  style={{ borderColor: "var(--baseline)", color: "var(--ink-2)" }}
                >
                  <CloseIcon />
                  Close
                </button>
              </div>
              <div className="min-h-0 flex-1">{expanded}</div>
              <div className={reserve}>{legend}</div>
              {footnote && (
                <p className={`mt-3 text-[0.8rem] ${reserve}`} style={{ color: "var(--ink-2)" }}>
                  {footnote}
                </p>
              )}
              {info && <InfoPopover label={infoLabel ?? "About this chart"}>{info}</InfoPopover>}
            </div>
          )}
        </dialog>
      )}
    </section>
  );
}
