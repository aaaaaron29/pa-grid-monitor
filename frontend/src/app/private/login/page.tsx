import { loginAction } from "./actions";

export default async function LoginPage({ searchParams }: PageProps<"/private/login">) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : "/private/zones";
  const error = params.error === "1";

  return (
    <main className="mx-auto flex max-w-[420px] flex-col px-4 py-24">
      <h1 className="mb-2 text-xl font-bold">Private access</h1>
      <p className="mb-6 text-sm" style={{ color: "var(--ink-2)" }}>
        PJM zone-level data (LMP, load) is gated here, not public -- see the note on the home
        page about PJM&apos;s non-member redistribution terms.
      </p>
      <form action={loginAction} className="flex flex-col gap-3">
        <input type="hidden" name="next" value={next} />
        <input
          type="password"
          name="passcode"
          placeholder="Passcode"
          autoFocus
          required
          className="rounded-md border px-3 py-2"
          style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
        />
        {error && <p className="text-sm" style={{ color: "var(--red)" }}>Wrong passcode.</p>}
        <button
          type="submit"
          className="rounded-md px-3 py-2 font-semibold text-white"
          style={{ background: "var(--blue)" }}
        >
          Enter
        </button>
      </form>
    </main>
  );
}
