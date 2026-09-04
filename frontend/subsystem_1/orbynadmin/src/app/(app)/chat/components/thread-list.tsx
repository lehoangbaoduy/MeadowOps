"use client";

import { formatDistanceToNow } from "date-fns";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { personaLabel, type ChatThread } from "../types";

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
        No persona threads yet. The Builder opens a thread from Subsystem 2 once a scenario is active.
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-2 p-3">
        {threads.map((thread) => (
          <button
            key={thread.id}
            type="button"
            onClick={() => onSelect(thread.id)}
            className={cn(
              "flex flex-col items-start gap-1 rounded-lg border p-3 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground",
              selectedId === thread.id && "bg-muted"
            )}
          >
            <div className="flex w-full items-center gap-2">
              <span className="font-semibold">{personaLabel(thread.persona)}</span>
              {thread.unread_count > 0 && (
                <Badge className="ml-auto shrink-0">{thread.unread_count}</Badge>
              )}
            </div>
            <span className="text-xs text-muted-foreground">
              Opened {formatDistanceToNow(new Date(thread.created_at), { addSuffix: true })}
            </span>
          </button>
        ))}
      </div>
    </ScrollArea>
  );
}
