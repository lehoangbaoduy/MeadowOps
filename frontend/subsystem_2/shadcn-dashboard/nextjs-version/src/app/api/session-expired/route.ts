import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 20a (MEADOWOPS-UI-002): post-implementation code review, HIGH —
 * `(dashboard)/layout.tsx` cannot delete a cookie itself (Next.js only
 * allows cookie mutation from a Route Handler or Server Action, never
 * during a Server Component's render), so its `redirect("/sign-in")` on
 * a stale/expired/forged session left the bad cookie attached to the
 * browser. `middleware.ts`'s presence-only gate then saw that cookie on
 * `/sign-in` and bounced straight back to `/dashboard` — an unrecoverable
 * loop for any session that outlives its backend-verified JWT, which the
 * cookie's own lack of a matching `maxAge` guarantees will eventually
 * happen for every session. This route is the one place in the app that
 * can actually clear the cookie *and* redirect in the same response —
 * `(dashboard)/layout.tsx` now redirects here instead of straight to
 * `/sign-in`.
 */
export function GET(request: NextRequest): NextResponse {
  const response = NextResponse.redirect(new URL("/sign-in", request.url));
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
