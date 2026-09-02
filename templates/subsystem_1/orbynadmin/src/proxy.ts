import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Presence-only gate — the Edge runtime this proxy executes in doesn't
 * carry the real Builder token to compare against (that lives server-side,
 * in a Node runtime, via MEADOWOPS_BUILDER_TOKEN). A forged/stale cookie
 * value still gets past this check, but every actual data request goes
 * through src/lib/admin-api.ts, which forwards it to FastAPI's
 * require_builder — the real, only security boundary. This proxy only
 * avoids flashing an empty authenticated shell before that 401 comes back.
 *
 * File is named `proxy.ts`, exporting `proxy` — Next.js 16 renamed the
 * `middleware.ts`/`export function middleware` convention; the old file
 * name still builds but warns, and the old export name doesn't build at
 * all once the file is renamed.
 */
export function proxy(request: NextRequest): NextResponse {
  const isAuthed = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  const { pathname } = request.nextUrl;

  if (!isAuthed && pathname !== "/login") {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  if (isAuthed && pathname === "/login") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
