import { createHash, timingSafeEqual } from "crypto";

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
  return Boolean(expected && token && safeEqual(token, expected));
}

/** Constant-time string comparison, so response timing reveals nothing about how much of a
 *  guess was right. Both sides here are fixed-length hex digests; anything else is unequal. */
export function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

const DEFAULT_NEXT = "/private/zones";

/** Where to send someone after signing in. Only same-site paths under /private/ are allowed;
 *  anything else (another site, a protocol-relative "//host" URL, a login-page loop) falls back
 *  to the default, so a crafted link cannot bounce a visitor to an outside site. */
export function safeNext(raw: unknown): string {
  if (typeof raw !== "string") return DEFAULT_NEXT;
  if (!raw.startsWith("/private/") || raw.startsWith("/private/login")) return DEFAULT_NEXT;
  if (/[\\\u0000-\u001f]/.test(raw)) return DEFAULT_NEXT;
  return raw;
}
