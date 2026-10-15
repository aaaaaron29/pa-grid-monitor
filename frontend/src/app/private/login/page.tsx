import { loginAction } from "./actions";

export default async function LoginPage({ searchParams }: PageProps<"/private/login">) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : "/private/zones";
  const error = params.error === "1";

  return (
    <main className="mx-auto w-full flex max-w-[420px] flex-col px-4 py-16 sm:py-24">
      <h1 className="mb-2 text-xl font-bold">Private access</h1>
      <p className="mb-6 text-sm" style={{ color: "var(--ink-2)" }}>
        PJM zone-level data (LMP, load) is gated here, not public. See the note on the home
        page about PJM&apos;s non-member redistribution terms.
      </p>
      <form action={loginAction} className="flex flex-col gap-3">
        <label htmlFor="passcode" className="text-sm font-semibold">
          Passcode
        </label>
        <input type="hidden" name="next" value={next} />
        <input
          id="passcode"
          type="password"
          name="passcode"
          autoComplete="current-password"
          autoFocus
          required
          aria-invalid={error || undefined}
          aria-describedby={error ? "passcode-error" : undefined}
          className="rounded-md border px-3 py-2.5"
          style={{ borderColor: error ? "var(--red)" : "var(--baseline)", background: "var(--surface-1)" }}
        />
        {error && (
          <p id="passcode-error" role="alert" className="text-sm font-semibold" style={{ color: "var(--ink-1)" }}>
            Wrong passcode. Check it and try again.
          </p>
        )}
        <button
          type="submit"
          className="rounded-md px-3 py-2.5 font-semibold transition-[filter] duration-150 hover:brightness-110 active:brightness-95"
          style={{ background: "var(--ink-1)", color: "var(--page)" }}
        >
          Enter
        </button>
      </form>
    </main>
  );
}
