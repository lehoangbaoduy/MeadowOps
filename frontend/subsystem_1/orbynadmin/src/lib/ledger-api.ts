import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 24 (MEADOWOPS-DOM-018) / Unit 34 (write actions): server-side proxy
 * for the Decision & Event Ledger API, same convention as src/lib/
 * admin-api.ts - the Activity page is an async Server Component that calls
 * listDecisions directly (reads the httpOnly session cookie via
 * next/headers, forwards it as the real Bearer token); write actions are
 * called from client components via this app's own /api/ledger/* route
 * handlers, which call the functions below. All write routes are
 * require_admin on the backend (app.api.ledger) - a non-Builder session
 * gets the same 403 the backend already enforces, surfaced through
 * extractErrorMessage the same way scenario-actions.tsx does in
 * Subsystem 2.
 */
async function ledgerFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return Response.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) {
    return Response.json({ detail: "Server is not configured" }, { status: 500 });
  }

  return fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    // Reflects the live ledger state - never serve a stale cached read.
    cache: "no-store",
  });
}

export function listDecisions(): Promise<Response> {
  return ledgerFetch("/api/v1/ledger/decisions");
}

export function proposeDecision(body: unknown): Promise<Response> {
  return ledgerFetch("/api/v1/ledger/decisions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function requestClarification(decisionId: string): Promise<Response> {
  return ledgerFetch(
    `/api/v1/ledger/decisions/${encodeURIComponent(decisionId)}/request-clarification`,
    { method: "POST" }
  );
}

export function resubmitDecision(decisionId: string): Promise<Response> {
  return ledgerFetch(`/api/v1/ledger/decisions/${encodeURIComponent(decisionId)}/resubmit`, {
    method: "POST",
  });
}

export function acceptDecision(decisionId: string, approvalAuthority?: string): Promise<Response> {
  return ledgerFetch(`/api/v1/ledger/decisions/${encodeURIComponent(decisionId)}/accept`, {
    method: "POST",
    body: JSON.stringify(
      approvalAuthority ? { approval_authority: approvalAuthority } : {}
    ),
  });
}

export function rejectDecision(decisionId: string): Promise<Response> {
  return ledgerFetch(`/api/v1/ledger/decisions/${encodeURIComponent(decisionId)}/reject`, {
    method: "POST",
  });
}

export function markImplemented(decisionId: string): Promise<Response> {
  return ledgerFetch(`/api/v1/ledger/decisions/${encodeURIComponent(decisionId)}/implement`, {
    method: "POST",
  });
}

export function markPartiallyImplemented(decisionId: string): Promise<Response> {
  return ledgerFetch(
    `/api/v1/ledger/decisions/${encodeURIComponent(decisionId)}/partially-implement`,
    { method: "POST" }
  );
}

export function recordOutcome(
  decisionId: string,
  outcome: string,
  notes: string | null
): Promise<Response> {
  return ledgerFetch(`/api/v1/ledger/decisions/${encodeURIComponent(decisionId)}/outcome`, {
    method: "POST",
    body: JSON.stringify({ outcome, notes }),
  });
}
