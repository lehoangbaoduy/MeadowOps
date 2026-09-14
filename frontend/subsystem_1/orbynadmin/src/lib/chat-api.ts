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

export function sendMessage(
  threadId: string,
  body: string,
  attachmentId?: string
): Promise<Response> {
  return chatFetch(`/api/v1/chat/threads/${encodeURIComponent(threadId)}/messages`, {
    method: "POST",
    body: JSON.stringify(attachmentId ? { body, attachment_id: attachmentId } : { body }),
  });
}

export function mintWsTicket(): Promise<Response> {
  return chatFetch("/api/v1/chat/ws-ticket", { method: "POST" });
}

// Unit 34 (PRD 6.10): the Analyst's own seven-question reflection on a
// completed thread. Not routed through app/lib/portfolio - this is the
// Analyst-voiced write half (app.api.portfolio's reject_service_role
// route), never the require_admin compiled export the Builder reads in
// Subsystem 2 (see docs/data-flow.md's own audience split for why those
// two stay on separate routes/apps).
export function submitReflection(threadId: string, body: unknown): Promise<Response> {
  return chatFetch(`/api/v1/portfolio/threads/${encodeURIComponent(threadId)}/reflection`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Unit 30b (MEADOWOPS-UI-004, PRD 6.1 "Drafting" bullet, catalog row 31,
// B12 follow-on to U30): the Analyst's own not-yet-sent reply for a
// thread, persisted server-side (per (thread_id, user_id)) so it survives
// past this browser. A localStorage buffer sits in front of this in the
// composer itself for true network-interruption resilience — this call is
// the periodic sync, not the only line of defense.
export function saveDraft(threadId: string, body: string): Promise<Response> {
  return chatFetch(`/api/v1/chat/threads/${encodeURIComponent(threadId)}/draft`, {
    method: "PUT",
    body: JSON.stringify({ body }),
  });
}

// Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
// a separate fetch, not chatFetch above - chatFetch always forces
// Content-Type: application/json, which would corrupt a multipart upload
// (the backend needs the browser-generated multipart boundary in that
// header, not a JSON content type). `fetch` sets that header itself from
// the FormData body when none is supplied, so it's deliberately omitted
// here.
export async function uploadAttachment(threadId: string, formData: FormData): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return Response.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) {
    return Response.json({ detail: "Server is not configured" }, { status: 500 });
  }
  return fetch(
    `${baseUrl}/api/v1/chat/threads/${encodeURIComponent(threadId)}/attachments`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: formData }
  );
}

// Not routed through chatFetch either - the response here is the raw file
// (binary content, its own Content-Type/Content-Disposition headers), not
// JSON, so there's nothing for chatFetch's forced request Content-Type to
// help with and the proxy route (app/api/chat/messages/[id]/attachment)
// needs the unmodified Response to read headers off of directly.
export async function getAttachment(messageId: string): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return Response.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) {
    return Response.json({ detail: "Server is not configured" }, { status: 500 });
  }
  return fetch(`${baseUrl}/api/v1/chat/messages/${encodeURIComponent(messageId)}/attachment`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
}
