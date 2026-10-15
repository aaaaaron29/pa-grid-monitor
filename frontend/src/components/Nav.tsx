"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { STATIC_DEMO } from "@/lib/staticDemo";

// The passcode-gated area does not exist in the static snapshot, so its link is added only
// when STATIC_DEMO is false. Built this way (rather than filtered at runtime) the minifier
// drops the link and its route string from the snapshot's JavaScript entirely.
const PRIVATE_LINK = {
  href: "/private/zones",
  label: "Private",
  match: (p: string) => p.startsWith("/private"),
};

const LINKS = [
  { href: "/", label: "Case study", match: (p: string) => p === "/" },
  { href: "/demand", label: "PJM demand", match: (p: string) => p.startsWith("/demand") },
  { href: "/map", label: "PA map", match: (p: string) => p.startsWith("/map") },
  ...(STATIC_DEMO ? [] : [PRIVATE_LINK]),
];

export function Nav() {
  const pathname = usePathname();
  const links = LINKS;

  return (
    <header className="border-b" style={{ borderColor: "var(--border)" }}>
      <div className="mx-auto flex max-w-[1100px] flex-wrap items-center justify-between gap-x-6 gap-y-1 px-4 py-4">
        <Link href="/" className="font-bold text-[var(--ink-1)]">
          Grid Watch
        </Link>
        <nav aria-label="Primary" className="flex gap-5 text-sm">
          {links.map((l) => {
            const active = l.match(pathname);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className="py-1 underline-offset-[6px] hover:text-[var(--ink-1)] aria-[current=page]:font-semibold aria-[current=page]:underline"
                style={{ color: active ? "var(--ink-1)" : "var(--ink-2)", textDecorationColor: "var(--blue)" }}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
