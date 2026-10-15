"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { COOKIE_NAME, expectedToken, safeEqual, safeNext, tokenForPasscode } from "@/lib/auth";
import {
  LOCK_MINUTES,
  MAX_FAILURES,
  clearFailures,
  clientKey,
  lockedMinutes,
  recordFailure,
} from "@/lib/lockout";

// redirect() works by throwing, so none of the redirects below sit inside a try block.
export async function loginAction(formData: FormData) {
  const passcode = String(formData.get("passcode") ?? "");
  const next = safeNext(formData.get("next"));
  const back = (query: string) => `/private/login?${query}&next=${encodeURIComponent(next)}`;

  // 1. Is this visitor already locked out? Checked before the passcode is even looked at, so a
  //    correct passcode does not get through during a lockout.
  let key: string;
  let lockedFor = 0;
  try {
    key = await clientKey();
    lockedFor = await lockedMinutes(key);
  } catch {
    // The lockout store is unreachable. Fail closed: no sign-in without the guard in place.
    redirect(back("error=unavailable"));
  }
  if (lockedFor > 0) redirect(back(`locked=${lockedFor}`));

  // 2. Check the passcode. An unset PRIVATE_PASSCODE means nothing can match (fail closed).
  const expected = expectedToken();
  const correct = Boolean(expected) && passcode !== "" && safeEqual(tokenForPasscode(passcode), expected!);

  if (!correct) {
    let result: { failures: number; locked: boolean };
    try {
      result = await recordFailure(key);
    } catch {
      redirect(back("error=unavailable"));
    }
    if (result.locked) redirect(back(`locked=${LOCK_MINUTES}`));
    redirect(back(`error=1&left=${MAX_FAILURES - result.failures}`));
  }

  // 3. Signed in: forget earlier typos, set the cookie, go where they were headed.
  try {
    await clearFailures(key);
  } catch {
    // Not worth refusing a correct passcode over; the record expires on its own.
  }
  const jar = await cookies();
  jar.set(COOKIE_NAME, expected!, {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
  redirect(next);
}
