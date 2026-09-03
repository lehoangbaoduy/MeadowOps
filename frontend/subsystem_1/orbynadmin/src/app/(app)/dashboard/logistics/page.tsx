import Link from "next/link";
import {
  IconCalendarStats,
  IconCircleCheck,
  IconClockHour4,
  IconPackageExport,
  IconTruckDelivery,
} from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { KpiCard } from "@/components/kpi-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getExecutiveSummary, getExecutiveTrend } from "@/lib/dashboard-api";
import { formatDays, formatPercent } from "@/lib/dashboard-format";
import { EXCEPTION_CATEGORY_LABEL, type ExecutiveKpi, type ExecutiveSummary } from "@/types/dashboard";

// PRD Appendix A — the five core KPIs, in the same order as Unit 10's
// backend/sql/kpi/ files (otif, fill_rate, days_of_supply, order_cycle_time,
// perfect_order_rate).
const KPI_CARDS = [
  { icon: IconTruckDelivery, label: "OTIF", unit: "", field: "otif_pct", color: "var(--chart-1)" },
  { icon: IconPackageExport, label: "Fill Rate", unit: "", field: "fill_rate_pct", color: "var(--chart-2)" },
  {
    icon: IconClockHour4,
    label: "Order Cycle Time",
    unit: "",
    field: "order_cycle_time_days",
    color: "var(--chart-4)",
  },
  {
    icon: IconCircleCheck,
    label: "Perfect Order Rate",
    unit: "",
    field: "perfect_order_rate_pct",
    color: "var(--chart-3)",
  },
] as const;

function trendFor(rows: ExecutiveKpi[], field: keyof ExecutiveKpi): number[] {
  return rows
    .map((row) => row[field])
    .filter((v): v is string => v != null)
    .map(Number);
}

export default async function LogisticsPage() {
  const [summaryResponse, trendResponse] = await Promise.all([getExecutiveSummary(), getExecutiveTrend()]);
  const summary: ExecutiveSummary = summaryResponse.ok
    ? await summaryResponse.json()
    : { kpis: null, open_exception_counts: [] };
  const trendRows: ExecutiveKpi[] = trendResponse.ok ? await trendResponse.json() : [];
  const kpis = summary.kpis;

  const values: Record<string, string | null> = {
    OTIF: formatPercent(kpis?.otif_pct ?? null),
    "Fill Rate": formatPercent(kpis?.fill_rate_pct ?? null),
    "Order Cycle Time": formatDays(kpis?.order_cycle_time_days ?? null),
    "Perfect Order Rate": formatPercent(kpis?.perfect_order_rate_pct ?? null),
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description={
          kpis
            ? `OTIF, fill rate and days-of-supply across the network — as of simulation date ${kpis.simulation_date}.`
            : "OTIF, fill rate and days-of-supply across the network."
        }
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {KPI_CARDS.map((kpi) => (
          <KpiCard
            key={kpi.label}
            icon={kpi.icon}
            label={kpi.label}
            unit={kpi.unit}
            value={values[kpi.label]}
            trend={trendFor(trendRows, kpi.field)}
            trendColor={kpi.color}
          />
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <IconCalendarStats className="size-4" />
            Open exceptions by category
          </CardTitle>
        </CardHeader>
        <CardContent>
          {summary.open_exception_counts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No open exceptions.</p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {summary.open_exception_counts.map((row) => (
                <Link key={row.category} href={`/reports?category=${row.category}`}>
                  <Badge variant={row.open_count > 0 ? "destructive" : "secondary"} className="h-7 gap-1.5 px-3 text-sm">
                    {EXCEPTION_CATEGORY_LABEL[row.category] ?? row.category}
                    <span className="font-semibold">{row.open_count}</span>
                  </Badge>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
