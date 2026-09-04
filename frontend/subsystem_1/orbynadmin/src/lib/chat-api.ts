import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 21 (MEADOWOPS-UI-003, PRD 6.13, S1-FR-15): the Analyst's side of the
 * persona-chat surface — proxies Unit 21a's chat REST routes exactly the
 * same way src/lib/admin-api.ts proxies the master-data routes. No
 * createThread here (unlike Subsystem 2's own chat-api.ts) — DD-25: the
 * Builder is the one who picks which thread to open, the Analyst only ever
 * replies to threads that already exist. The WebSocket itself is NOT
 * proxied here — see src/app/api/chat/ws-ticket/route.ts and
 * NEXT_PUBLIC_MEADOWOPS_WS_BASE_URL.
 */
async function chatFetch(path: string, init: RequestInit = {}): Promise<Response> {
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
    // Unread counts and new messages arrive continuously — never serve a
    // stale list back to the Analyst.
    cache: "no-store",
  });
}

export function listThreads(): Promise<Response> {
  return chatFetch("/api/v1/chat/threads");
}

export function markThreadRead(threadId: string): Promise<Response> {
  return chatFetch(`/api/v1/chat/threads/${encodeURIComponent(threadId)}/read`, {
    method: "POST",
  });
}

export function listMessages(threadId: string): Promise<Response> {
  return chatFetch(`/api/v1/chat/threads/${encodeURIComponent(threadId)}/messages`);
}

export function sendMessage(threadId: string, body: string): Promise<Response> {
  return chatFetch(`/api/v1/chat/threads/${encodeURIComponent(threadId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function mintWsTicket(): Promise<Response> {
  return chatFetch("/api/v1/chat/ws-ticket", { method: "POST" });
}
