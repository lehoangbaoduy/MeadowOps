import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 24 (MEADOWOPS-DOM-018): server-side proxy for the Decision & Event
 * Ledger's read routes, same convention as src/lib/dashboard-api.ts - the
 * Activity page is an async Server Component that calls listDecisions
 * directly (reads the httpOnly session cookie via next/headers, forwards
 * it as the real Bearer token). Only the read route is wired here - write
 * actions (propose/accept/reject/...) have no UI entry point yet (see
 * tests/frontend/test_activity_page.py's own docstring for why).
 */
async function ledgerFetch(path: string): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return Response.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) {
    return Response.json({ detail: "Server is not configured" }, { status: 500 });
  }

  return fetch(`${baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    // Reflects the live ledger state - never serve a stale cached read.
    cache: "no-store",
  });
}

export function listDecisions(): Promise<Response> {
  return ledgerFetch("/api/v1/ledger/decisions");
}
