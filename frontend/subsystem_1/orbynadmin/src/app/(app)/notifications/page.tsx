import { IconBell } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { listNotificationFeed } from "@/lib/chat-api";
import type { NotificationFeedItem } from "@/lib/notification-feed";
import { NotificationsList } from "./notifications-list";

// Unit 39 (MEADOWOPS-DOM-027): the real feed - deadline notifications plus
// replies the user has not read. Previously a static placeholder.
export default async function NotificationsPage() {
  const response = await listNotificationFeed();
  const items: NotificationFeedItem[] = response.ok ? await response.json() : [];
  if (!response.ok) {
    console.error("Failed to load notifications:", response.status);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description="Deadlines coming up and replies waiting for you."
      />
      {items.length === 0 ? (
        <EmptyState
          icon={IconBell}
          title="You're all caught up"
          description="New replies and response deadlines show up here when there is something to act on."
        />
      ) : (
        <NotificationsList initialItems={items} />
      )}
    </div>
  );
}
