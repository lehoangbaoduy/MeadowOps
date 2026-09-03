import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 20a (MEADOWOPS-UI-002): every scenario builder request is proxied
 * server-side through here, forwarding this app's own session cookie as
 * an `Authorization: Bearer` header — same shape as orbynadmin's
 * `src/lib/admin-api.ts` (Unit 8/17a/19). No new backend routes: this
 * calls Unit 18's existing `/api/v1/admin/scenarios/*` (require_admin)
 * and Unit 16's `/api/v1/dashboard/exceptions` (require_authenticated)
 * exactly as they already exist — U20's internal_service_token/
 * ASGITransport mechanism is unrelated, that's for Subsystem 2's own
 * server-side engine logic (Phase 3), not a human Builder's browser
 * session.
 */
async function scenarioFetch(path: string, init: RequestInit = {}): Promise<Response> {
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
    // Scenario status can change from another tab/session at any time —
    // never serve a stale list/detail back to the Builder.
    cache: "no-store",
  });
}

export function listScenarios(statusFilter?: string): Promise<Response> {
  const query = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return scenarioFetch(`/api/v1/admin/scenarios${query}`);
}

export function getScenario(id: string): Promise<Response> {
  return scenarioFetch(`/api/v1/admin/scenarios/${encodeURIComponent(id)}`);
}

export function createScenario(body: unknown): Promise<Response> {
  return scenarioFetch("/api/v1/admin/scenarios", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateGroundTruth(id: string, body: unknown): Promise<Response> {
  return scenarioFetch(`/api/v1/admin/scenarios/${encodeURIComponent(id)}/ground-truth`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function regenerateScenario(id: string): Promise<Response> {
  return scenarioFetch(`/api/v1/admin/scenarios/${encodeURIComponent(id)}/regenerate`, {
    method: "POST",
  });
}

export function approveScenario(id: string): Promise<Response> {
  return scenarioFetch(`/api/v1/admin/scenarios/${encodeURIComponent(id)}/approve`, {
    method: "POST",
  });
}

export function activateScenario(id: string): Promise<Response> {
  return scenarioFetch(`/api/v1/admin/scenarios/${encodeURIComponent(id)}/activate`, {
    method: "POST",
  });
}

export function cancelScenario(id: string): Promise<Response> {
  return scenarioFetch(`/api/v1/admin/scenarios/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}

/**
 * Backs the "select" control (PRD 6.4) — a real browsable/filterable
 * picker over open exception flags, not a plain ID input (pre-scoping
 * decision, this unit). Defaults to open flags only, matching
 * create_scenario_from_exception_flag's own requirement that the source
 * flag still be open.
 */
export function listOpenExceptions(category?: string): Promise<Response> {
  const params = new URLSearchParams({ include_resolved: "false", limit: "200" });
  if (category) params.set("category", category);
  return scenarioFetch(`/api/v1/dashboard/exceptions?${params.toString()}`);
}
