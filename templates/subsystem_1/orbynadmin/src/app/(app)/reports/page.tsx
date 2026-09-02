import { IconReportAnalytics } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export default function ReportsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Data quality — exception and conflicting-source reporting."
      />
      <EmptyState
        icon={IconReportAnalytics}
        title="No reports yet"
        description="Exception and data-quality reports appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
