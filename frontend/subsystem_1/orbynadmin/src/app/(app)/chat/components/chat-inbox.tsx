"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ThreadList } from "./thread-list";
import { ThreadView } from "./thread-view";
import { useChatSocket, type ChatSocketFrame } from "../use-chat-socket";
import type { ChatMessage, ChatThread } from "../types";

async function fetchThreads(): Promise<ChatThread[]> {
  const response = await fetch("/api/chat/threads", { cache: "no-store" });
  if (!response.ok) return [];
  return response.json();
}

async function fetchMessages(threadId: string): Promise<ChatMessage[]> {
  const response = await fetch(`/api/chat/threads/${threadId}/messages`, { cache: "no-store" });
  if (!response.ok) return [];
  return response.json();
}

export function ChatInbox({ initialThreads }: { initialThreads: ChatThread[] }) {
  const [threads, setThreads] = useState(initialThreads);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  // Code review (2026-09-03): a fresh GET /threads — from the WS handler's
  // "not the open thread" branch, or the 30s poll below — can resolve
  // after selectThread's own optimistic zero and briefly restore a stale
  // non-zero count on the thread the viewer currently has open. The
  // client is the authority on "I'm looking at this one right now," so
  // every threads-list update forces the selected thread's count to 0
  // rather than trusting whatever the server happened to return.
  const selectedIdRef = useRef<string | null>(null);
  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const applyThreads = useCallback((fetched: ChatThread[]) => {
    setThreads(
      fetched.map((thread) =>
        thread.id === selectedIdRef.current ? { ...thread, unread_count: 0 } : thread
      )
    );
  }, []);

  // Security review (2026-09-03): the open-thread branch of handleFrame
  // below fires a mark-read POST on every single broadcast frame with no
  // debounce — a burst of messages arriving close together (or several
  // viewers with the same thread open) turns into that many redundant
  // writes. The upsert itself is cheap and idempotent, but there's no
  // rate limiting anywhere on the chat REST surface to fall back on, so
  // this collapses a burst into one trailing call instead.
  const markReadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const markReadDebounced = useCallback((threadId: string) => {
    if (markReadTimerRef.current) clearTimeout(markReadTimerRef.current);
    markReadTimerRef.current = setTimeout(() => {
      void fetch(`/api/chat/threads/${threadId}/read`, { method: "POST" });
    }, 500);
  }, []);
  useEffect(() => {
    return () => {
      if (markReadTimerRef.current) clearTimeout(markReadTimerRef.current);
    };
  }, []);

  const selectedThread = threads.find((thread) => thread.id === selectedId) ?? null;

  const selectThread = useCallback(async (threadId: string) => {
    setSelectedId(threadId);
    const history = await fetchMessages(threadId);
    setMessages(history);
    await fetch(`/api/chat/threads/${threadId}/read`, { method: "POST" });
    setThreads((prev) =>
      prev.map((thread) => (thread.id === threadId ? { ...thread, unread_count: 0 } : thread))
    );
  }, []);

  const handleSend = useCallback(
    // Unit 30c (MEADOWOPS-UI-005, B12 follow-on to U30): attachmentId is
    // optional - the already-uploaded, not-yet-claimed ChatAttachment's id
    // (see thread-view.tsx's own upload flow).
    async (body: string, attachmentId?: string): Promise<boolean> => {
      if (!selectedId) return false;
      const response = await fetch(`/api/chat/threads/${selectedId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(attachmentId ? { body, attachment_id: attachmentId } : { body }),
      });
      if (!response.ok) return false;
      const message: ChatMessage = await response.json();
      setMessages((prev) => (prev.some((m) => m.id === message.id) ? prev : [...prev, message]));
      return true;
    },
    [selectedId]
  );

  const handleFrame = useCallback(
    (frame: ChatSocketFrame) => {
      if (frame.thread_id === selectedId) {
        setMessages((prev) =>
          prev.some((m) => m.id === frame.message_id)
            ? prev
            : [
                ...prev,
                {
                  id: frame.message_id,
                  thread_id: frame.thread_id,
                  // The WS frame doesn't carry the sender's user id (only
                  // sender_role) — never a real UUID, never read anywhere;
                  // rendering keys off sender_role instead.
                  sender_user_id: "",
                  sender_role: frame.sender_role,
                  body: frame.body,
                  attachment_ref: frame.attachment_ref,
                  sent_at: frame.sent_at,
                },
              ]
        );
        // Already viewing this thread — re-mark read rather than let a
        // frame sent by this same viewer (the registry broadcasts to every
        // connection, including the sender's own) bump its own badge.
        markReadDebounced(frame.thread_id);
        return;
      }
      // Not the open thread — refetch for an authoritative unread count
      // rather than guessing whether this frame was sent by us.
      void fetchThreads().then(applyThreads);
    },
    [selectedId, applyThreads, markReadDebounced]
  );

  useChatSocket(handleFrame);

  useEffect(() => {
    const interval = setInterval(() => {
      void fetchThreads().then(applyThreads);
    }, 30000);
    return () => clearInterval(interval);
  }, [applyThreads]);

  return (
    <div className="grid h-[calc(100vh-10rem)] grid-cols-[280px_1fr] overflow-hidden rounded-lg border">
      <div className="border-r">
        <ThreadList threads={threads} selectedId={selectedId} onSelect={selectThread} />
      </div>
      <ThreadView thread={selectedThread} messages={messages} onSend={handleSend} />
    </div>
  );
}
