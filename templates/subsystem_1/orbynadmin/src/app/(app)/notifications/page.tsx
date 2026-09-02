import { IconBell } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export default function NotificationsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description="Admin-side exception alert feed."
      />
      <EmptyState
        icon={IconBell}
        title="No notifications yet"
        description="Exception alerts appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
