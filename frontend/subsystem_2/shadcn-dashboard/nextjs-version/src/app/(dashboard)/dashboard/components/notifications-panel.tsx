"use client"

import { useState } from "react"
import Link from "next/link"
import { formatDistanceToNow } from "date-fns"
import { Bell, Clock } from "lucide-react"

import { cn } from "@/lib/utils"
import { notificationLabel, personaLabel, type ChatThread, type Notification } from "../../mail/data"

interface NotificationsPanelProps {
  notifications: Notification[];
  threadsById: Record<string, ChatThread>;
}

// Unit 30a (MEADOWOPS-UI-003, PRD 6.1): "Home page: Open Threads, Company
// Status, Notifications, Completed Work." The Builder's deadline_missed
// feed — app.services.notifications._recipient_ids notifies the Builder
// when a thread the Analyst hasn't responded to goes overdue. NotificationRead
// only carries thread_id, so the persona label is joined client-side against
// the threads already fetched for this page (page.tsx), rather than showing
// an unlabeled row.
export function NotificationsPanel({ notifications, threadsById }: NotificationsPanelProps) {
  const [readIds, setReadIds] = useState<Set<string>>(
    () => new Set(notifications.filter((n) => n.read_at).map((n) => n.id))
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

  if (notifications.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-10 text-center">
        <Bell className="size-6 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">No notifications</p>
      </div>
    );
  }

  return (
    <ul className="flex flex-col divide-y rounded-lg border">
      {notifications.map((notification) => {
        const thread = threadsById[notification.thread_id];
        const isRead = readIds.has(notification.id);
        return (
          <li
            key={notification.id}
            className={cn("flex items-start gap-3 px-4 py-3 text-sm", !isRead && "bg-muted/40")}
          >
            <Clock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <div className="flex-1 space-y-0.5">
              <p className="font-medium">
                {notificationLabel(notification.kind)}
                {thread ? ` — ${personaLabel(thread.persona)}` : ""}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(notification.created_at), { addSuffix: true })}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <Link href="/mail" className="text-xs text-primary hover:underline">
                Open
              </Link>
              {!isRead && (
                <button
                  type="button"
                  onClick={() => void handleMarkRead(notification.id)}
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
