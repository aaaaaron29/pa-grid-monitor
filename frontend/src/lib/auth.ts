import { createHash } from "crypto";

// Single shared passcode gating /private/*, not a multi-user system (see
// ARCHITECTURE.md Section 9 item 7). The cookie never stores the plaintext passcode --
// it stores a hash of it, which also means rotating PRIVATE_PASSCODE invalidates every
// existing cookie automatically, with no separate revocation step needed.

export const COOKIE_NAME = "gw_private";

function hash(passcode: string): string {
  return createHash("sha256").update(`gw:${passcode}`).digest("hex");
}

// Fails closed: an unset/empty PRIVATE_PASSCODE means no value can ever match, so
// /private/* stays unreachable rather than silently accepting any cookie.
export function expectedToken(): string | null {
  const passcode = process.env.PRIVATE_PASSCODE;
  return passcode ? hash(passcode) : null;
}

export function tokenForPasscode(passcode: string): string {
  return hash(passcode);
}

export function isValidToken(token: string | undefined | null): boolean {
  const expected = expectedToken();
  return Boolean(expected && token && token === expected);
}
