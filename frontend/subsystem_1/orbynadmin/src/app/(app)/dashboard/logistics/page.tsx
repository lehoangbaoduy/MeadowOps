import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import {
  DeliveriesCard,
  KpiTrendCard,
  NewExceptionsCard,
  OrderActivityCard,
  OrderStatusCard,
  ShipmentOutcomeCard,
} from "@/components/overview/activity-charts";
import {
  OpenExceptionsCard,
  TopProductsCard,
  WarehouseStockCard,
} from "@/components/overview/network-charts";
import { OverviewKpis } from "@/components/overview/overview-kpis";
import { SupplierTable } from "@/components/overview/supplier-table";
import { getOverview } from "@/lib/dashboard-api";
import { formatDate } from "@/lib/dashboard-format";
import { cn } from "@/lib/utils";
import type { Overview } from "@/types/dashboard";

const WINDOW_OPTIONS = [7, 30, 90] as const;
const DEFAULT_WINDOW = 30;

function parseWindow(value: string | undefined): number {
  const days = Number(value);
  return (WINDOW_OPTIONS as readonly number[]).includes(days) ? days : DEFAULT_WINDOW;
}

/**
 * Unit 41: the Overview. Every number and chart is an aggregate of the
 * trailing window of real simulation data, read in one call from
 * GET /api/v1/dashboard/overview - nothing here is estimated or invented.
 */
export default async function OverviewPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const days = parseWindow((await searchParams).days);
  const response = await getOverview(days);
  if (!response.ok) {
    return (
      <div className="space-y-6">
        <PageHeader title="Overview" />
        <p role="alert" className="rounded-lg border border-destructive/40 p-6 text-sm text-destructive">
          The overview could not be loaded. Try again in a moment.
        </p>
      </div>
    );
  }
  const overview: Overview = await response.json();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description={`Company status for ${formatDate(overview.window_start)} – ${formatDate(overview.as_of)} (simulation dates)`}
      >
        <nav aria-label="Time window" className="inline-flex rounded-lg border p-0.5">
          {WINDOW_OPTIONS.map((option) => (
            <Link
              key={option}
              href={`/dashboard/logistics?days=${option}`}
              aria-current={option === days ? "page" : undefined}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                option === days
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {option}d
            </Link>
          ))}
        </nav>
      </PageHeader>

      {overview.window_days < days && (
        <p className="text-xs text-muted-foreground">
          The simulation only has {overview.window_days} day{overview.window_days === 1 ? "" : "s"} of
          history, so that is all this view covers.
        </p>
      )}

      <OverviewKpis overview={overview} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <KpiTrendCard rows={overview.kpi_trend} />
        <ShipmentOutcomeCard breakdown={overview.shipment_delivery} />
        <OrderActivityCard days={overview.daily_activity} />
        <DeliveriesCard days={overview.daily_activity} />
        <OrderStatusCard statuses={overview.sales_order_status} />
        <WarehouseStockCard warehouses={overview.inventory_by_warehouse} />
        <TopProductsCard products={overview.top_products} />
        <OpenExceptionsCard counts={overview.open_exceptions_by_category} />
        <NewExceptionsCard days={overview.new_exceptions_per_day} />
        <SupplierTable suppliers={overview.suppliers} />
      </div>
    </div>
  );
}
