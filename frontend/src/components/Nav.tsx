import Link from "next/link";

export function Nav() {
  return (
    <header className="border-b" style={{ borderColor: "var(--border)" }}>
      <div className="mx-auto flex max-w-[1100px] items-center justify-between px-4 py-4">
        <Link href="/" className="font-bold">
          Grid Watch
        </Link>
        <nav className="flex gap-5 text-sm" style={{ color: "var(--ink-2)" }}>
          <Link href="/">Case study</Link>
          <Link href="/demand">PJM demand</Link>
          <Link href="/private/zones">Private</Link>
        </nav>
      </div>
    </header>
  );
}
