import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 21 (MEADOWOPS-UI-003, PRD 6.13, DD-25): the Builder's side of the
 * persona-chat surface — proxies Unit 21a's chat REST routes exactly the
 * same way src/lib/scenario-api.ts proxies the scenario builder routes.
 * The WebSocket itself is NOT proxied here (a Next.js server action can't
 * hold a live upstream connection open for a browser client) — mintWsTicket
 * only mints the short-lived ticket server-side; the browser then connects
 * directly to the backend (see app/api/chat/ws-ticket/route.ts and
 * NEXT_PUBLIC_MEADOWOPS_WS_BASE_URL).
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
    // stale list back to the Builder.
    cache: "no-store",
  });
}

export function listThreads(): Promise<Response> {
  return chatFetch("/api/v1/chat/threads");
}

export function createThread(scenarioId: string, persona: string): Promise<Response> {
  return chatFetch("/api/v1/chat/threads", {
    method: "POST",
    body: JSON.stringify({ scenario_id: scenarioId, persona }),
  });
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

// Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): the Builder's own notification
// feed — deadline_missed (a thread the Builder is responsible for chasing)
// rows only, per app.services.notifications.sweep_thread_deadlines's
// recipient split.
export function listNotifications(): Promise<Response> {
  return chatFetch("/api/v1/chat/notifications");
}

export function markNotificationRead(notificationId: string): Promise<Response> {
  return chatFetch(
    `/api/v1/chat/notifications/${encodeURIComponent(notificationId)}/read`,
    { method: "POST" }
  );
}

// Unit 30b (MEADOWOPS-UI-004, PRD 6.1 "Drafting" bullet, catalog row 31,
// B12 follow-on to U30): the Builder's own not-yet-sent persona message
// for a thread, persisted server-side (per (thread_id, user_id)) so it
// survives past this browser. A localStorage buffer sits in front of
// this in the composer itself for true network-interruption resilience —
// this call is the periodic sync, not the only line of defense.
export function saveDraft(threadId: string, body: string): Promise<Response> {
  return chatFetch(`/api/v1/chat/threads/${encodeURIComponent(threadId)}/draft`, {
    method: "PUT",
    body: JSON.stringify({ body }),
  });
}

// Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
// download-only here - attachments are Analyst-side upload (S1-FR-15's own
// wording), so this app (the Builder's) never gets an uploadAttachment
// counterpart, only the read path both roles share. Not routed through
// chatFetch: the response here is the raw file (its own Content-Type/
// Content-Disposition headers), not JSON, so chatFetch's forced request
// Content-Type would help with nothing and the proxy route (app/api/chat/
// messages/[id]/attachment) needs the unmodified Response to read headers
// off of directly.
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
