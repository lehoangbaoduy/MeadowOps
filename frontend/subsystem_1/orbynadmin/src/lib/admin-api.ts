import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 8 (MEADOWOPS-API-002): every admin master-data request is proxied
 * server-side through here — the browser calls our own /api/admin/* route
 * handlers, which call this, which calls the FastAPI backend. Unit 17a
 * (MEADOWOPS-DOM-010): the token forwarded below is now a signed session
 * token minted by the backend at login (app.core.security), not a static
 * shared secret — the backend verifies it and enforces role
 * (require_authenticated/require_admin) on every route; this module still
 * just forwards whatever the httpOnly cookie holds, read from the
 * *request* cookie jar so a request without a valid session is rejected
 * before ever reaching the backend.
 */
async function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
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
    // Master data can be edited from the admin panel itself — never serve a
    // stale cached list back to the Builder.
    cache: "no-store",
  });
}

export function listMasterData(entity: string): Promise<Response> {
  return adminFetch(`/api/v1/admin/${entity}`);
}

export function createMasterData(entity: string, body: unknown): Promise<Response> {
  return adminFetch(`/api/v1/admin/${entity}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateMasterData(entity: string, id: string, body: unknown): Promise<Response> {
  return adminFetch(`/api/v1/admin/${entity}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/**
 * Unit 19 (MEADOWOPS-DOM-012, PRD 5.9): Query Playground — every route
 * here is require_authenticated on the backend (Analyst and Admin both),
 * unlike the master-data routes above. Reuses the same adminFetch proxy
 * (the name is a Unit 8 leftover — it just forwards the session cookie,
 * nothing admin-specific about it).
 */
export function executeQuery(sql: string, confirmed: boolean): Promise<Response> {
  return adminFetch("/api/v1/query/execute", {
    method: "POST",
    body: JSON.stringify({ sql, confirmed }),
  });
}

export function cancelQueryConfirmation(sql: string): Promise<Response> {
  return adminFetch("/api/v1/query/cancel-confirmation", {
    method: "POST",
    body: JSON.stringify({ sql }),
  });
}

export function refreshSandbox(): Promise<Response> {
  return adminFetch("/api/v1/query/refresh-sandbox", { method: "POST" });
}

export function getQueryHistory(): Promise<Response> {
  return adminFetch("/api/v1/query/history");
}
