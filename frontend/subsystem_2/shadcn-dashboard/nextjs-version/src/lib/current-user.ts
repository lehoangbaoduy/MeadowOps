import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 20a (MEADOWOPS-UI-002): server-side role lookup, calling the
 * backend's own `/api/v1/me` with the session cookie rather than decoding
 * the token locally — an expired/invalid/missing session reads as `null`
 * the same way a real write request would be rejected. Mirrors
 * orbynadmin's `src/lib/current-user.ts` (Unit 17a), but here it is also
 * this app's actual enforcement boundary (see `(dashboard)/layout.tsx`),
 * not just UI gating: `/api/login` already refuses to set the cookie for
 * a non-admin (pre-implementation security review, CRITICAL fix), so a
 * non-`admin` role reaching here means the cookie was forged, stale
 * against a since-changed account, or came from a stray non-app cookie —
 * every one of those cases must still be rejected on every page load.
 */
export async function getCurrentRole(): Promise<string | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;

  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) return null;

  // Code review, MEDIUM: an unreachable backend must not throw out of a
  // Server Component render (no error.tsx existed to catch it) — treated
  // the same as an invalid session, since either way this request can't
  // be authenticated right now.
  try {
    const response = await fetch(`${baseUrl}/api/v1/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!response.ok) return null;

    const body = await response.json();
    return typeof body.role === "string" ? body.role : null;
  } catch {
    return null;
  }
}
