import { IconChartBar } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { KpiTrendChart } from "@/components/kpi-trend-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getExecutiveTrend } from "@/lib/dashboard-api";
import type { ExecutiveKpi } from "@/types/dashboard";

export default async function AnalyticsPage() {
  const response = await getExecutiveTrend();
  const rows: ExecutiveKpi[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title="Analytics" description="Drill down into KPI trends over time." />
      {rows.length === 0 ? (
        <EmptyState
          icon={IconChartBar}
          title="No trend data yet"
          description="KPI trends appear here once the scheduler's first tick has run (app.domain.scheduler)."
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">
              OTIF · Fill Rate · Perfect Order Rate, by simulation date
            </CardTitle>
          </CardHeader>
          <CardContent>
            <KpiTrendChart rows={rows} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
