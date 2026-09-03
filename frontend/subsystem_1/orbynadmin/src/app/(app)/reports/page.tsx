import { IconReportAnalytics } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { ExceptionsTable } from "@/components/exceptions-table";
import { listExceptions } from "@/lib/dashboard-api";
import { EXCEPTION_CATEGORY_LABEL, type ExceptionFlag } from "@/types/dashboard";

export default async function ReportsPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string }>;
}) {
  const { category } = await searchParams;
  const response = await listExceptions({ category });
  const exceptions: ExceptionFlag[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description={
          category
            ? `Data quality — filtered to ${EXCEPTION_CATEGORY_LABEL[category] ?? category}.`
            : "Data quality — exception and conflicting-source reporting."
        }
      />
      {exceptions.length === 0 ? (
        <EmptyState
          icon={IconReportAnalytics}
          title="No open exceptions"
          description="Exceptions appear here once the exception engine's next evaluation flags one (app.services.exception_engine)."
        />
      ) : (
        <ExceptionsTable exceptions={exceptions} />
      )}
    </div>
  );
}
