import { IconChartBar } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export default function AnalyticsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        description="Drill down into KPI trends over time."
      />
      <EmptyState
        icon={IconChartBar}
        title="No trend data yet"
        description="KPI trend charts appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
