import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { COOKIE_NAME, isValidToken } from "@/lib/auth";

// Gates everything under /private/*. Runs in the Node.js runtime (Proxy's default as of
// Next.js 16), so it can use Node's crypto module directly -- see lib/auth.ts.
export const config = {
  matcher: ["/private/:path*"],
};

export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname === "/private/login") {
    return NextResponse.next();
  }

  const token = request.cookies.get(COOKIE_NAME)?.value;
  if (!isValidToken(token)) {
    const url = new URL("/private/login", request.url);
    url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}
