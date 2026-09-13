"use client";

import { useEffect, useRef, useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { IconAlertTriangle, IconClock, IconLoader2, IconPaperclip, IconX } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  clearDraftBuffer,
  loadDraftBuffer,
  saveDraftBuffer,
  syncDraftToServer,
} from "../composer-draft";
import { MAX_MESSAGE_BODY_LENGTH, personaLabel, type ChatMessage, type ChatThread } from "../types";

// Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
// mirrors app.domain.attachment_validation.ALLOWED_CONTENT_TYPES exactly -
// this is a browser file-picker hint only (the `accept` attribute), never
// itself a security boundary; the backend re-validates every byte via
// magic-byte sniffing regardless of what the picker allowed through.
const ATTACHMENT_ACCEPT = "image/jpeg,image/png,image/gif,application/pdf,text/csv";

// Unit 30b (MEADOWOPS-UI-004, PRD 6.1, B12): matches chat-inbox.tsx's own
// markReadDebounced precedent — collapse a burst of keystrokes into one
// trailing sync call rather than one PUT per character.
const DRAFT_SYNC_DEBOUNCE_MS = 500;

// Unit 30a (MEADOWOPS-UI-003, PRD 6.1): "Response windows... surfaced as a
// deadline banner on the open thread." is_overdue is the backend's own
// moment-of-response computation (app.api.chat._is_overdue) — this banner
// never recomputes it client-side, so it can go briefly stale between the
// 30s thread-list poll (chat-inbox.tsx) without disagreeing with the
// server about what "overdue" means.
function DeadlineBanner({ thread }: { thread: ChatThread }) {
  if (!thread.deadline_at) return null;
  const deadline = new Date(thread.deadline_at);
  if (thread.is_overdue) {
    return (
      <div className="flex items-center gap-2 border-b bg-destructive/10 px-4 py-2 text-sm text-destructive">
        <IconAlertTriangle className="size-4 shrink-0" />
        <span>Response overdue — was due {formatDistanceToNow(deadline, { addSuffix: true })}</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 border-b bg-amber-500/10 px-4 py-2 text-sm text-amber-700 dark:text-amber-400">
      <IconClock className="size-4 shrink-0" />
      <span>Response due {formatDistanceToNow(deadline, { addSuffix: true })}</span>
    </div>
  );
}

export function ThreadView({
  thread,
  messages,
  onSend,
}: {
  thread: ChatThread | null;
  messages: ChatMessage[];
  onSend: (body: string, attachmentId?: string) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(false);
  // Unit 30c (MEADOWOPS-UI-005, B12 follow-on to U30): an already-uploaded,
  // not-yet-sent attachment - the two-phase flow migration 0026's own
  // docstring explains (upload first, claim it at send time). Cleared on
  // thread switch and after a successful send; NOT cleared on a failed
  // send, same "don't silently discard what the user did" reasoning the
  // draft-preservation fix above already established for the body text.
  const [pendingAttachment, setPendingAttachment] = useState<
    { id: string; filename: string } | null
  >(null);
  const [uploading, setUploading] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncAbortRef = useRef<AbortController | null>(null);
  // Code review (this unit, MEDIUM): the args of a debounced sync not yet
  // fired — flushed immediately (bypassing the debounce) on thread switch
  // or unmount, rather than dropped, so a quick switch right after typing
  // doesn't leave the server copy permanently one edit behind.
  const pendingSyncRef = useRef<{ threadId: string; body: string } | null>(null);

  function fireSync(id: string, body: string) {
    syncAbortRef.current?.abort();
    const controller = new AbortController();
    syncAbortRef.current = controller;
    pendingSyncRef.current = null;
    void syncDraftToServer(id, body, controller.signal);
  }

  // Unit 30b (MEADOWOPS-UI-004, PRD 6.1 "Drafting" bullet, catalog row 31):
  // restore this thread's own draft whenever it's opened or switched to —
  // ThreadView isn't remounted on thread switch (chat-inbox.tsx renders one
  // long-lived instance), so without this, the previous thread's unsent
  // text would otherwise carry over into the newly-selected thread's
  // composer. The localStorage buffer (this browser's most current copy,
  // written on every keystroke) wins over thread.draft_body (only as fresh
  // as the last successful periodic server sync) when both exist — but
  // only when a buffer actually exists (`!== null`); a buffer holding ""
  // means the user deliberately cleared it, which must NOT fall through
  // to a stale server value (code review, this unit, HIGH).
  useEffect(() => {
    if (!thread) {
      setDraft("");
      return;
    }
    const buffered = loadDraftBuffer(thread.id);
    setDraft(buffered !== null ? buffered : thread.draft_body);
    setError(false);
    // Unit 30c (MEADOWOPS-UI-005): unlike the draft buffer, a pending
    // attachment has no per-thread persistence of its own (it's already
    // durably stored server-side the moment upload succeeds - only the
    // *pairing* with a not-yet-sent message is local UI state) - switching
    // threads with one still attached leaves it uploaded-but-unclaimed
    // forever, the same accepted orphan-row outcome as abandoning a
    // compose entirely (ChatAttachment's own docstring).
    setPendingAttachment(null);
    setAttachError(null);
    return () => {
      if (syncTimerRef.current) {
        clearTimeout(syncTimerRef.current);
        syncTimerRef.current = null;
      }
      if (pendingSyncRef.current) {
        fireSync(pendingSyncRef.current.threadId, pendingSyncRef.current.body);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thread?.id]);

  if (!thread) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a thread to view its history.
      </div>
    );
  }
  // TypeScript doesn't carry the null-narrowing above into the closures
  // below (thread is a parameter, not a local const) — capture the id
  // once here rather than asserting non-null at every call site.
  const threadId = thread.id;

  async function handleFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Reset the input's own value so re-picking the exact same file (e.g.
    // after removing it) still fires this handler again - browsers don't
    // fire onChange for a no-op reselection otherwise.
    event.target.value = "";
    if (!file) return;
    setAttachError(null);
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch(`/api/chat/threads/${threadId}/attachments`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setAttachError(
          typeof payload?.detail === "string"
            ? payload.detail
            : "Couldn't attach that file — try again."
        );
        return;
      }
      const attachment: { id: string; original_filename: string } = await response.json();
      setPendingAttachment({ id: attachment.id, filename: attachment.original_filename });
    } catch {
      setAttachError("Couldn't attach that file — try again.");
    } finally {
      setUploading(false);
    }
  }

  function handleDraftChange(value: string) {
    setDraft(value);
    setError(false);
    saveDraftBuffer(threadId, value);
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    pendingSyncRef.current = { threadId, body: value };
    syncTimerRef.current = setTimeout(() => {
      syncTimerRef.current = null;
      fireSync(threadId, value);
    }, DRAFT_SYNC_DEBOUNCE_MS);
  }

  async function handleSend() {
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    // Code review (this unit, HIGH): cancel any not-yet-fired debounced sync
    // and abort the browser->proxy leg of any in-flight one before sending.
    // Known residual gap (advisor review, this unit): aborting here only
    // cancels the browser->Next.js-proxy fetch — the proxy's own downstream
    // fetch to the backend is not connected to this AbortSignal, so a sync
    // that had already reached the proxy by the time Send is clicked can
    // still complete server-side after send_message's transactional
    // draft-clear, leaving a stale draft row behind. This is a narrow
    // window (bounded by DRAFT_SYNC_DEBOUNCE_MS plus one network hop) and
    // its only effect is a stale *draft* reappearing on next load — the
    // sent message itself is never affected. Accepted at this project's
    // scale rather than threading an AbortSignal through the proxy route or
    // adding a server-side send-vs-draft ordering guard; revisit if this
    // ever proves reachable in practice.
    if (syncTimerRef.current) {
      clearTimeout(syncTimerRef.current);
      syncTimerRef.current = null;
    }
    pendingSyncRef.current = null;
    syncAbortRef.current?.abort();
    // Code review (2026-09-03): only clear the draft once the send is
    // confirmed to have succeeded — a failed send (e.g. a 422 from
    // exceeding MAX_MESSAGE_BODY_LENGTH, or a transient 5xx) used to clear
    // the draft unconditionally, silently discarding what the user typed.
    try {
      const ok = await onSend(body, pendingAttachment?.id);
      setError(!ok);
      if (ok) {
        setDraft("");
        // send_message already clears the server-side draft row in the
        // same transaction as the send (app.services.chat.send_message) —
        // only the local buffer needs an explicit clear here.
        clearDraftBuffer(threadId);
        // Unit 30c (MEADOWOPS-UI-005): the attachment is now claimed by
        // the sent message server-side (app.services.chat.send_message) -
        // clear the local pairing so the next message doesn't also try to
        // claim it (send_message would reject that as
        // AttachmentAlreadyLinkedError anyway, but clearing here avoids
        // ever sending a doomed request).
        setPendingAttachment(null);
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="p-4">
        <h2 className="text-lg font-semibold">{personaLabel(thread.persona)}</h2>
      </div>
      <DeadlineBanner thread={thread} />
      <Separator />
      <ScrollArea className="flex-1 p-4">
        <div className="flex flex-col gap-3">
          {messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                "max-w-[75%] rounded-lg border p-3 text-sm",
                message.sender_role === "analyst" ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"
              )}
            >
              <p className="whitespace-pre-wrap">{message.body}</p>
              {message.attachment_ref && (
                <a
                  href={`/api/chat/messages/${message.id}/attachment`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 flex items-center gap-1 text-xs underline opacity-80 hover:opacity-100"
                >
                  <IconPaperclip className="size-3" />
                  Attachment
                </a>
              )}
              <p className="mt-1 text-right text-xs opacity-70">
                {format(new Date(message.sent_at), "PPp")}
              </p>
            </div>
          ))}
        </div>
      </ScrollArea>
      <Separator />
      <div className="p-4">
        <div className="grid gap-2">
          <Textarea
            value={draft}
            onChange={(event) => handleDraftChange(event.target.value)}
            placeholder={`Reply as the Analyst...`}
            maxLength={MAX_MESSAGE_BODY_LENGTH}
            className="min-h-20"
          />
          {error && (
            <p className="text-sm text-destructive">
              Couldn&rsquo;t send that message. Your draft is still here — try again.
            </p>
          )}
          {attachError && <p className="text-sm text-destructive">{attachError}</p>}
          {pendingAttachment && (
            <div className="flex items-center gap-2 rounded-md border bg-muted px-2 py-1 text-xs">
              <IconPaperclip className="size-3 shrink-0" />
              <span className="truncate">{pendingAttachment.filename}</span>
              <button
                type="button"
                onClick={() => setPendingAttachment(null)}
                aria-label="Remove attachment"
                className="ml-auto text-muted-foreground hover:text-foreground"
              >
                <IconX className="size-3" />
              </button>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept={ATTACHMENT_ACCEPT}
            hidden
            onChange={handleFileSelected}
          />
          <div className="flex items-center justify-between">
            {/* Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380): this page
                is the Analyst's reply interface (personaLabel/placeholder
                above already assume that role) - the attach control is
                shown unconditionally rather than fetching the viewer's own
                role first (no such client-side role-awareness exists
                anywhere else in this app today, see nav-user.tsx's own
                static "Builder" label); a non-Analyst session using this
                page would see the same 403 the upload route already
                enforces server-side, surfaced through attachError above. */}
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={uploading || !!pendingAttachment}
              onClick={() => fileInputRef.current?.click()}
            >
              {uploading ? (
                <IconLoader2 className="size-4 animate-spin" />
              ) : (
                <IconPaperclip className="size-4" />
              )}
              Attach
            </Button>
            <Button onClick={handleSend} disabled={sending || !draft.trim()}>
              Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
