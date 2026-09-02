import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 8 (MEADOWOPS-API-002): every admin master-data request is proxied
 * server-side through here — the browser calls our own /api/admin/* route
 * handlers, which call this, which calls the FastAPI backend. The real
 * Builder bearer token (MEADOWOPS_BUILDER_TOKEN, server-only env var) never
 * leaves the Next.js server; the browser only ever holds the httpOnly
 * session cookie, whose value happens to equal that token (see
 * src/lib/session.ts) but is read here from the *request* cookie jar, not
 * re-read from env — so a request without a valid session is rejected
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
