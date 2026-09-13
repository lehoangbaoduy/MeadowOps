"use client";

import { useEffect, useRef } from "react";

/**
 * Unit 21 (MEADOWOPS-UI-003, PRD 6.13): live delivery for the Builder's
 * thread monitor. The browser cannot go through this app's own server-side
 * proxy (src/lib/chat-api.ts) for a WebSocket — a Next.js route handler
 * can't hold a live upstream connection open on the client's behalf — so
 * this connects directly to the FastAPI backend
 * (NEXT_PUBLIC_MEADOWOPS_WS_BASE_URL), after minting a fresh ticket
 * server-side through /api/chat/ws-ticket on every connection attempt.
 * Tickets are single-use with a 20s TTL (app/core/ws_tickets.py), so one is
 * never reused across a reconnect.
 */
export type ChatSocketFrame = {
  type: "chat.message";
  thread_id: string;
  message_id: string;
  sender_role: "admin" | "analyst";
  body: string;
  // Unit 30c (MEADOWOPS-UI-005, B12 follow-on to U30): mirrors
  // app.api.chat.create_message_route's broadcast payload — without this,
  // a message sent with an attachment would render with no attachment
  // link at all on every connection that receives it live, since mail.tsx's
  // handleFrame is what actually wins the race against the POST response
  // for the sender's own optimistic update.
  attachment_ref: string | null;
  sent_at: string;
};

const RECONNECT_DELAY_MS = 2000;

export function useChatSocket(onFrame: (frame: ChatSocketFrame) => void): void {
  const onFrameRef = useRef(onFrame);
  // Synced in an effect, not assigned inline during render (React 19's
  // react-hooks/refs rule flags a ref write during render even though the
  // connect() effect below only ever reads it asynchronously, from a
  // WebSocket event callback — never during a render pass).
  useEffect(() => {
    onFrameRef.current = onFrame;
  });

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    async function connect(): Promise<void> {
      if (stopped) return;
      // Code review (2026-09-03): everything past the fetch — a network
      // failure, a non-JSON body, or new WebSocket() itself throwing when
      // NEXT_PUBLIC_MEADOWOPS_WS_BASE_URL is unset — used to be an
      // unhandled rejection that silently killed reconnection forever,
      // since only the !ok branch below scheduled a retry. Every failure
      // path now falls through to the same retry.
      try {
        const ticketResponse = await fetch("/api/chat/ws-ticket", { method: "POST" });
        if (!ticketResponse.ok) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
          return;
        }
        const { ticket } = (await ticketResponse.json()) as { ticket: string };
        if (stopped) return;

        const wsBase = process.env.NEXT_PUBLIC_MEADOWOPS_WS_BASE_URL;
        socket = new WebSocket(`${wsBase}/api/v1/chat/ws/chat?ticket=${encodeURIComponent(ticket)}`);
        socket.onmessage = (event: MessageEvent<string>) => {
          const frame = JSON.parse(event.data) as ChatSocketFrame;
          onFrameRef.current(frame);
        };
        socket.onclose = () => {
          if (!stopped) reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        };
      } catch {
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    }

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);
}
