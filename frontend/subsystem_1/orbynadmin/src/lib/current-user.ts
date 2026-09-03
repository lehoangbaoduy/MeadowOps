import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 17a (MEADOWOPS-DOM-010, PRD 5.1/8.4 amendment, DD-22): server-side
 * role lookup for UI gating (hiding Admin-only controls from the
 * Analyst) — never the enforcement boundary itself. The real boundary is
 * FastAPI's require_admin on the write routes (app/core/auth.py); this
 * only decides what a Server Component renders. Calls the backend's own
 * /api/v1/me with the session cookie rather than decoding the token
 * locally, so an expired/invalid/missing session reads as `null` exactly
 * the same way a write request would be rejected.
 */
export async function getCurrentRole(): Promise<string | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;

  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) return null;

  const response = await fetch(`${baseUrl}/api/v1/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) return null;

  const body = await response.json();
  return typeof body.role === "string" ? body.role : null;
}
