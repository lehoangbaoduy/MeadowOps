"use client"

import { formatDistanceToNow } from "date-fns"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { personaLabel, type ChatThread } from "../data"

export function ThreadList({
  threads,
  selectedId,
  onSelect,
}: {
  threads: ChatThread[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (threads.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-muted-foreground">
        No threads yet — open one with &ldquo;New thread&rdquo; above.
      </div>
    );
  }

  return (
    <ScrollArea className="h-[calc(100vh-14rem)]">
      <div className="flex flex-col gap-2 p-4 pt-0">
        {threads.map((thread) => (
          <button
            key={thread.id}
            type="button"
            onClick={() => onSelect(thread.id)}
            className={cn(
              "hover:bg-accent hover:text-accent-foreground flex flex-col items-start gap-1 rounded-lg border p-3 text-left text-sm transition-all cursor-pointer",
              selectedId === thread.id && "bg-muted"
            )}
          >
            <div className="flex w-full items-center gap-2">
              <span className="font-semibold">{personaLabel(thread.persona)}</span>
              {thread.unread_count > 0 && (
                <Badge className="ml-auto shrink-0 cursor-pointer">{thread.unread_count}</Badge>
              )}
            </div>
            <span className="text-muted-foreground text-xs">
              Opened {formatDistanceToNow(new Date(thread.created_at), { addSuffix: true })}
            </span>
          </button>
        ))}
      </div>
    </ScrollArea>
  );
}
