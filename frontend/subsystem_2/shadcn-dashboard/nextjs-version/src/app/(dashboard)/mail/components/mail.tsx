"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { SuggestResult, SufficiencyResult } from "./ai-assist-panel"
import { NewThreadDialog } from "./new-thread-dialog"
import { ThreadList } from "./thread-list"
import { ThreadView } from "./thread-view"
import { useChatSocket, type ChatSocketFrame } from "../use-chat-socket"
import type { Attitude, ChatMessage, ChatThread, Persona, ScenarioOption } from "../data"

// Unit 35 (follow-on to Unit 23): shared by all three AI-assist actions -
// each backend route (suggest-opening/suggest-pushback/sufficiency-check)
// returns a JSON body with a `detail` string on every non-2xx status
// (FastAPI's own HTTPException shape), so this is the one place that turns
// "whatever went wrong" into the text AiAssistPanel shows the Builder,
// rather than duplicating this per action.
async function _aiErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // response body wasn't JSON - fall through to the generic message
  }
  return `Request failed (${response.status})`;
}

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

interface MailProps {
  threads: ChatThread[];
  scenarios: ScenarioOption[];
  defaultLayout?: number[];
}

export function Mail({ threads: initialThreads, scenarios, defaultLayout = [32, 68] }: MailProps) {
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

  const handleCreateThread = useCallback(
    async (scenarioId: string, persona: Persona) => {
      const response = await fetch("/api/chat/threads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: scenarioId, persona }),
      });
      if (!response.ok) return;
      // POST /chat/threads proxies the backend's ThreadRead shape, which
      // has no unread_count/draft_body fields (those are computed only by
      // the list endpoint's ThreadReadWithUnread) - casting the raw JSON
      // straight to ChatThread left both undefined on a just-created
      // thread. Selecting it immediately (below) fed that undefined
      // draft_body into ThreadView's draft state, which crashed with
      // "Cannot read properties of undefined (reading 'trim')" the moment
      // Send was clicked - reproduced live, root-caused to this gap. A
      // brand-new thread always has 0 unread messages and no draft, so
      // fill in the same defaults the backend's own list query would.
      const raw = await response.json();
      const thread: ChatThread = { ...raw, unread_count: raw.unread_count ?? 0, draft_body: raw.draft_body ?? "" };
      setThreads((prev) => (prev.some((t) => t.id === thread.id) ? prev : [thread, ...prev]));
      await selectThread(thread.id);
    },
    [selectThread]
  );

  const handleSend = useCallback(
    async (body: string): Promise<boolean> => {
      if (!selectedId) return false;
      const response = await fetch(`/api/chat/threads/${selectedId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      if (!response.ok) return false;
      const message: ChatMessage = await response.json();
      setMessages((prev) => (prev.some((m) => m.id === message.id) ? prev : [...prev, message]));
      return true;
    },
    [selectedId]
  );

  const handleSuggestOpening = useCallback(
    async (attitude: Attitude): Promise<SuggestResult> => {
      if (!selectedId) return { ok: false, error: "No thread selected." };
      const response = await fetch(`/api/chat/threads/${selectedId}/suggest-opening`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attitude }),
      });
      if (!response.ok) return { ok: false, error: await _aiErrorDetail(response) };
      const body = await response.json();
      return { ok: true, message: body.suggested_message };
    },
    [selectedId]
  );

  const handleSuggestPushback = useCallback(
    async (attitude: Attitude): Promise<SuggestResult> => {
      if (!selectedId) return { ok: false, error: "No thread selected." };
      const response = await fetch(`/api/chat/threads/${selectedId}/suggest-pushback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attitude }),
      });
      if (!response.ok) return { ok: false, error: await _aiErrorDetail(response) };
      const body = await response.json();
      return { ok: true, message: body.suggested_message };
    },
    [selectedId]
  );

  const handleCheckSufficiency = useCallback(async (): Promise<SufficiencyResult> => {
    if (!selectedId) return { ok: false, error: "No thread selected." };
    const response = await fetch(`/api/chat/threads/${selectedId}/sufficiency-check`, {
      method: "POST",
    });
    if (!response.ok) return { ok: false, error: await _aiErrorDetail(response) };
    const body = await response.json();
    return { ok: true, verdict: body.verdict, suggestedPushback: body.suggested_pushback };
  }, [selectedId]);

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

  const unreadThreads = threads.filter((thread) => thread.unread_count > 0);

  return (
    <TooltipProvider delayDuration={0}>
      <ResizablePanelGroup
        direction="horizontal"
        onLayout={(sizes: number[]) => {
          document.cookie = `react-resizable-panels:layout:mail=${JSON.stringify(sizes)}`;
        }}
        className="h-full items-stretch rounded-lg border overflow-hidden"
      >
        <ResizablePanel defaultSize={defaultLayout[0]} minSize={22} maxSize={40}>
          <Tabs defaultValue="all" className="gap-1">
            <div className="flex items-center px-4 py-1.5">
              <h1 className="text-foreground text-xl font-bold">Threads</h1>
              <TabsList className="ml-auto">
                <TabsTrigger value="all" className="cursor-pointer">All</TabsTrigger>
                <TabsTrigger value="unread" className="cursor-pointer">Unread</TabsTrigger>
              </TabsList>
            </div>
            <Separator />
            <div className="p-3">
              <NewThreadDialog scenarios={scenarios} onCreate={handleCreateThread} />
            </div>
            <TabsContent value="all" className="m-0">
              <ThreadList threads={threads} selectedId={selectedId} onSelect={selectThread} />
            </TabsContent>
            <TabsContent value="unread" className="m-0">
              <ThreadList threads={unreadThreads} selectedId={selectedId} onSelect={selectThread} />
            </TabsContent>
          </Tabs>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={defaultLayout[1]} minSize={30}>
          <ThreadView
            thread={selectedThread}
            messages={messages}
            onSend={handleSend}
            onSuggestOpening={handleSuggestOpening}
            onSuggestPushback={handleSuggestPushback}
            onCheckSufficiency={handleCheckSufficiency}
          />
        </ResizablePanel>
      </ResizablePanelGroup>
    </TooltipProvider>
  );
}
