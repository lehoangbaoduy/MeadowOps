import {
  IconAlertTriangle,
  IconCash,
  IconCircleCheck,
  IconClockHour4,
  IconPackageExport,
  IconShoppingCart,
  IconTruckDelivery,
  IconTruckLoading,
  type TablerIcon,
} from "@tabler/icons-react";

import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { formatCompactCurrency } from "@/lib/dashboard-format";
import { cn } from "@/lib/utils";
import type { Overview, OverviewKpiPoint } from "@/types/dashboard";

type KpiField = "otif_pct" | "fill_rate_pct" | "order_cycle_time_days" | "perfect_order_rate_pct";

const KPI_CARDS: {
  icon: TablerIcon;
  label: string;
  field: KpiField;
  suffix: string;
  color: string;
  higherIsBetter: boolean;
}[] = [
  { icon: IconTruckDelivery, label: "OTIF", field: "otif_pct", suffix: "%", color: "var(--chart-1)", higherIsBetter: true },
  { icon: IconPackageExport, label: "Fill rate", field: "fill_rate_pct", suffix: "%", color: "var(--chart-2)", higherIsBetter: true },
  { icon: IconClockHour4, label: "Order cycle time", field: "order_cycle_time_days", suffix: "d", color: "var(--chart-4)", higherIsBetter: false },
  { icon: IconCircleCheck, label: "Perfect order rate", field: "perfect_order_rate_pct", suffix: "%", color: "var(--chart-3)", higherIsBetter: true },
];

function series(points: OverviewKpiPoint[], field: KpiField): number[] {
  return points.map((p) => p[field]).filter((v): v is string => v != null).map(Number);
}

function Change({ values, suffix, higherIsBetter }: { values: number[]; suffix: string; higherIsBetter: boolean }) {
  if (values.length < 2) return null;
  const delta = values[values.length - 1] - values[0];
  if (Math.abs(delta) < 0.05) {
    return <p className="px-6 pb-4 text-xs text-muted-foreground">No change over the window</p>;
  }
  const isGood = higherIsBetter ? delta > 0 : delta < 0;
  const unit = suffix === "%" ? " pts" : suffix;
  return (
    <p className={cn("px-6 pb-4 text-xs font-medium", isGood ? "text-emerald-600 dark:text-emerald-400" : "text-destructive")}>
      {delta > 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}
      {unit} <span className="font-normal text-muted-foreground">since the window began</span>
    </p>
  );
}

function StatTile({ icon: Icon, label, value, hint }: { icon: TablerIcon; label: string; value: string; hint: string }) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 pt-6">
        <div className="rounded-md bg-muted p-2">
          <Icon className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-xl font-semibold tabular-nums">{value}</p>
          <p className="truncate text-xs text-muted-foreground">{hint}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function OverviewKpis({ overview }: { overview: Overview }) {
  const points = overview.kpi_trend;
  const latest = points[points.length - 1];
  const orders = overview.daily_activity.reduce((sum, d) => sum + d.orders_placed, 0);
  const value = overview.daily_activity.reduce((sum, d) => sum + Number(d.order_value), 0);
  const { delivered_on_time: onTime, delivered_late: late } = overview.shipment_delivery;
  const delivered = onTime + late;
  const openExceptions = overview.open_exceptions_by_category.reduce((sum, c) => sum + c.open_count, 0);
  const days = overview.window_days;

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {KPI_CARDS.map((kpi) => {
          const values = series(points, kpi.field);
          const current = latest?.[kpi.field];
          return (
            <div key={kpi.label} className="rounded-xl border bg-card">
              <KpiCard
                icon={kpi.icon}
                label={kpi.label}
                unit={current != null ? kpi.suffix : ""}
                value={current ?? null}
                trend={values}
                trendColor={kpi.color}
              />
              <Change values={values} suffix={kpi.suffix} higherIsBetter={kpi.higherIsBetter} />
            </div>
          );
        })}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile icon={IconShoppingCart} label={`Orders placed (${days}d)`} value={orders.toLocaleString("en-US")} hint="Sales orders, all customers" />
        <StatTile icon={IconCash} label={`Order value (${days}d)`} value={formatCompactCurrency(value)} hint="Quantity ordered × unit price" />
        <StatTile
          icon={IconTruckLoading}
          label="Deliveries on time"
          value={delivered > 0 ? `${((onTime / delivered) * 100).toFixed(1)}%` : "—"}
          hint={delivered > 0 ? `${onTime} of ${delivered} delivered` : "Nothing delivered yet"}
        />
        <StatTile icon={IconAlertTriangle} label="Open exceptions" value={String(openExceptions)} hint="Flagged and not yet cleared" />
      </div>
    </>
  );
}
