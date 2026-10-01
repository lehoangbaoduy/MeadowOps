"use client";

import * as React from "react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { IconClock, IconMessage } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { notificationTitle, type NotificationFeedItem } from "@/lib/notification-feed";
import { cn } from "@/lib/utils";

export function NotificationsList({ initialItems }: { initialItems: NotificationFeedItem[] }) {
  const [readIds, setReadIds] = React.useState<Set<string>>(
    () => new Set(initialItems.filter((item) => item.is_read).map((item) => item.id))
  );

  async function markRead(id: string) {
    setReadIds((prev) => new Set(prev).add(id));
    const response = await fetch(`/api/notifications/${id}/read`, { method: "POST" });
    if (!response.ok) {
      setReadIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  return (
    <Card>
      <CardContent className="divide-y p-0">
        {initialItems.map((item) => {
          const isRead = readIds.has(item.id);
          // A reply clears itself once the thread is opened; only deadline
          // notifications are stored rows that need an explicit mark-read.
          const canMarkRead = item.kind !== "new_reply" && !isRead;
          return (
            <div
              key={item.id}
              className={cn("flex items-start gap-3 px-4 py-3 text-sm", !isRead && "bg-muted/40")}
            >
              {item.kind === "new_reply" ? (
                <IconMessage className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              ) : (
                <IconClock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              )}
              <div className="flex-1 space-y-0.5">
                <p className={cn(!isRead && "font-medium")}>{notificationTitle(item)}</p>
                <p className="text-xs text-muted-foreground">
                  {item.scenario_title} ·{" "}
                  {formatDistanceToNow(new Date(item.occurred_at), { addSuffix: true })}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Button asChild variant="link" size="sm" className="h-auto p-0">
                  <Link href="/chat">Open</Link>
                </Button>
                {canMarkRead && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    onClick={() => void markRead(item.id)}
                  >
                    Mark read
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
