"use client"

import { useState } from "react"
import Link from "next/link"
import { formatDistanceToNow } from "date-fns"
import { Bell, Clock, MessageSquare } from "lucide-react"

import { cn } from "@/lib/utils"
import { feedItemTitle, type NotificationFeedItem } from "../../mail/data"

interface NotificationsPanelProps {
  items: NotificationFeedItem[];
}

// Unit 39 (PRD 6.1): what needs the Builder's attention - overdue/approaching
// response deadlines and unread Analyst replies. Reply items clear by reading
// the thread (opening it in Chat), deadline items can also be marked read here.
export function NotificationsPanel({ items }: NotificationsPanelProps) {
  const [readIds, setReadIds] = useState<Set<string>>(
    () => new Set(items.filter((item) => item.is_read).map((item) => item.id))
  );

  async function handleMarkRead(id: string) {
    if (readIds.has(id)) return;
    setReadIds((prev) => new Set(prev).add(id));
    const response = await fetch(`/api/chat/notifications/${id}/read`, { method: "POST" });
    if (!response.ok) {
      setReadIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-10 text-center">
        <Bell className="size-6 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">Nothing needs your attention</p>
        <p className="max-w-sm text-xs text-muted-foreground">
          Analyst replies and response deadlines show up here.
        </p>
      </div>
    );
  }

  return (
    <ul className="flex flex-col divide-y rounded-lg border">
      {items.map((item) => {
        const isRead = readIds.has(item.id);
        const isReply = item.kind === "new_reply";
        const Icon = isReply ? MessageSquare : Clock;
        return (
          <li
            key={item.id}
            className={cn("flex items-start gap-3 px-4 py-3 text-sm", !isRead && "bg-muted/40")}
          >
            <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <div className="flex-1 space-y-0.5">
              <p className="font-medium">{feedItemTitle(item)}</p>
              <p className="text-xs text-muted-foreground">
                {item.scenario_title} ·{" "}
                {formatDistanceToNow(new Date(item.occurred_at), { addSuffix: true })}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <Link href="/mail" className="text-xs text-primary hover:underline">
                Open
              </Link>
              {!isRead && !isReply && (
                <button
                  type="button"
                  onClick={() => void handleMarkRead(item.id)}
                  className="text-xs text-muted-foreground hover:underline cursor-pointer"
                >
                  Mark read
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
