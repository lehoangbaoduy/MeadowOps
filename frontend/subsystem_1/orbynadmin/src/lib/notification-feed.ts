import { personaLabel } from "@/app/(app)/chat/types";

/** Mirrors app.schemas.chat.NotificationFeedItemRead (Unit 39). */
export type NotificationFeedItem = {
  id: string;
  kind: "deadline_approaching" | "deadline_missed" | "new_reply";
  thread_id: string;
  persona: string;
  scenario_title: string;
  unread_count: number;
  occurred_at: string;
  is_read: boolean;
};

export function notificationTitle(item: NotificationFeedItem): string {
  const who = personaLabel(item.persona);
  switch (item.kind) {
    case "new_reply":
      return item.unread_count > 1
        ? `${item.unread_count} new messages from ${who}`
        : `New message from ${who}`;
    case "deadline_approaching":
      return `Response due soon: ${who}`;
    case "deadline_missed":
      return `Response overdue: ${who}`;
  }
}

/** Items the user has not dealt with yet - what the header badge counts. */
export function unreadCount(items: NotificationFeedItem[]): number {
  return items.filter((item) => !item.is_read).length;
}
