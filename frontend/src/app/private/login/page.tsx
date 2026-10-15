import { loginAction } from "./actions";
import { safeNext } from "@/lib/auth";
import { LOCK_MINUTES, clientKey, lockedMinutes } from "@/lib/lockout";

// If the lockout store cannot be reached the page still renders; the sign-in action itself
// refuses to proceed without it.
async function currentLockMinutes(): Promise<number> {
  try {
    return await lockedMinutes(await clientKey());
  } catch {
    return 0;
  }
}

export default async function LoginPage({ searchParams }: PageProps<"/private/login">) {
  const params = await searchParams;
  const next = safeNext(params.next);

  const lockedFor = await currentLockMinutes();
  const locked = lockedFor > 0;
  const unavailable = params.error === "unavailable";
  const wrong = params.error === "1" && !locked;
  const left = Number(typeof params.left === "string" ? params.left : "");

  let message: string | null = null;
  if (locked) {
    message = `Too many wrong passcodes. Try again in ${lockedFor} ${lockedFor === 1 ? "minute" : "minutes"}.`;
  } else if (unavailable) {
    message = "Sign-in is temporarily unavailable. Try again in a moment.";
  } else if (wrong) {
    message =
      Number.isInteger(left) && left > 0
        ? `Wrong passcode. ${left} ${left === 1 ? "attempt" : "attempts"} left before a ${LOCK_MINUTES}-minute lockout.`
        : "Wrong passcode. Check it and try again.";
  }
  const hasError = message !== null;

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
          autoFocus={!locked}
          required
          disabled={locked}
          aria-invalid={hasError || undefined}
          aria-describedby={hasError ? "passcode-error" : undefined}
          className="rounded-md border px-3 py-2.5 disabled:opacity-60"
          style={{ borderColor: hasError ? "var(--red)" : "var(--baseline)", background: "var(--surface-1)" }}
        />
        {message && (
          <p id="passcode-error" role="alert" className="text-sm font-semibold" style={{ color: "var(--ink-1)" }}>
            {message}
          </p>
        )}
        <button
          type="submit"
          disabled={locked}
          className="rounded-md px-3 py-2.5 font-semibold transition-[filter] duration-150 hover:brightness-110 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100"
          style={{ background: "var(--ink-1)", color: "var(--page)" }}
        >
          Enter
        </button>
      </form>
    </main>
  );
}
