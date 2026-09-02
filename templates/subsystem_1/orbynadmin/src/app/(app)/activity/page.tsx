import { IconActivity } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export default function ActivityPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description="Decision & Event Ledger — a timestamped log of decisions and events."
      />
      <EmptyState
        icon={IconActivity}
        title="No activity yet"
        description="Ledger entries appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
