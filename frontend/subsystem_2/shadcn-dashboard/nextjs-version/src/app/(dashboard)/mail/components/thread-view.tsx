"use client"

import { useState } from "react"
import { format } from "date-fns"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { MAX_MESSAGE_BODY_LENGTH, personaLabel, type ChatMessage, type ChatThread } from "../data"

export function ThreadView({
  thread,
  messages,
  onSend,
}: {
  thread: ChatThread | null;
  messages: ChatMessage[];
  onSend: (body: string) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(false);

  if (!thread) {
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
        Select a thread, or start a new one, to see its history.
      </div>
    );
  }

  async function handleSend() {
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    // Code review (2026-09-03): only clear the draft once the send is
    // confirmed to have succeeded — a failed send (e.g. a 422 from
    // exceeding MAX_MESSAGE_BODY_LENGTH, or a transient 5xx) used to clear
    // the draft unconditionally, silently discarding what the user typed.
    try {
      const ok = await onSend(body);
      setError(!ok);
      if (ok) setDraft("");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center px-4 py-2">
        <h1 className="text-foreground text-xl font-bold">{personaLabel(thread.persona)}</h1>
      </div>
      <Separator />
      <ScrollArea className="flex-1 p-4">
        <div className="flex flex-col gap-3">
          {messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                "max-w-[75%] rounded-lg border p-3 text-sm",
                message.sender_role === "admin" ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"
              )}
            >
              <p className="whitespace-pre-wrap">{message.body}</p>
              <p className="mt-1 text-right text-xs opacity-70">
                {format(new Date(message.sent_at), "PPp")}
              </p>
            </div>
          ))}
        </div>
      </ScrollArea>
      <Separator className="mt-auto" />
      <div className="p-4">
        <div className="grid gap-2">
          <Textarea
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              setError(false);
            }}
            placeholder={`Reply as ${personaLabel(thread.persona)}'s Builder contact...`}
            maxLength={MAX_MESSAGE_BODY_LENGTH}
            className="min-h-20 cursor-text"
          />
          {error && (
            <p className="text-sm text-destructive">
              Couldn&rsquo;t send that message. Your draft is still here — try again.
            </p>
          )}
          <Button onClick={handleSend} disabled={sending || !draft.trim()} className="ml-auto cursor-pointer">
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}
