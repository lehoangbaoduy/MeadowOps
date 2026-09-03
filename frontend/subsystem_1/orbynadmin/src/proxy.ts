import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Presence-only gate — the Edge runtime this proxy executes in can't
 * verify the signed session token (that's a Node-runtime job, done
 * server-side by FastAPI's require_authenticated/require_admin,
 * app/core/auth.py, Unit 17a/MEADOWOPS-DOM-010). A forged/stale cookie
 * value still gets past this check, but every actual data request goes
 * through src/lib/admin-api.ts, which forwards it to the backend for real
 * verification — the real, only security boundary. This proxy only
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
