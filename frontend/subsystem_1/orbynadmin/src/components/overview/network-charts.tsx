"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { formatCompactNumber } from "@/lib/dashboard-format";
import {
  EXCEPTION_CATEGORY_LABEL,
  type ExceptionCountByCategory,
  type OverviewProductDemand,
  type OverviewWarehouse,
} from "@/types/dashboard";
import { ChartCard } from "./chart-card";

const AXIS = { tickLine: false, axisLine: false, tickMargin: 8 } as const;

const STOCK_CONFIG: ChartConfig = {
  units_on_hand: { label: "On hand", color: "var(--chart-1)" },
  units_allocated: { label: "Allocated to orders", color: "var(--chart-3)" },
};

export function WarehouseStockCard({ warehouses }: { warehouses: OverviewWarehouse[] }) {
  const data = warehouses.map((w) => ({ ...w, name: w.warehouse_name }));
  return (
    <ChartCard
      title="Stock by warehouse"
      description="Units on hand and units already allocated, from the latest stock snapshot"
      isEmpty={warehouses.every((w) => w.units_on_hand === 0 && w.units_allocated === 0)}
      emptyMessage="No stock has been recorded yet."
      className="xl:col-span-8"
    >
      <ChartContainer config={STOCK_CONFIG} className="aspect-auto h-[240px] w-full">
        <BarChart data={data} margin={{ left: 4, right: 4, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis width={44} tickFormatter={formatCompactNumber} {...AXIS} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="units_on_hand" fill="var(--color-units_on_hand)" radius={[4, 4, 0, 0]} maxBarSize={56} />
          <Bar dataKey="units_allocated" fill="var(--color-units_allocated)" radius={[4, 4, 0, 0]} maxBarSize={56} />
        </BarChart>
      </ChartContainer>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        {warehouses.map((w) => (
          <div key={w.warehouse_id} className="rounded-lg border px-3 py-2">
            <dt className="text-xs text-muted-foreground">{w.warehouse_name}</dt>
            <dd className="mt-0.5 text-sm">
              <span className="font-semibold tabular-nums">
                {w.avg_days_of_supply != null ? `${w.avg_days_of_supply} days` : "—"}
              </span>{" "}
              <span className="text-muted-foreground">avg supply</span>
              {w.low_stock_positions > 0 && (
                <span className="ml-2 text-xs font-medium text-destructive">
                  {w.low_stock_positions} low-stock
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </ChartCard>
  );
}

const PRODUCT_CONFIG: ChartConfig = {
  units_ordered: { label: "Ordered", color: "var(--chart-1)" },
  units_shipped: { label: "Shipped", color: "var(--chart-2)" },
};

export function TopProductsCard({ products }: { products: OverviewProductDemand[] }) {
  return (
    <ChartCard
      title="Most-ordered products"
      description="Units ordered versus units shipped so far, by product"
      isEmpty={products.length === 0}
      emptyMessage="No product demand in this window."
      className="xl:col-span-6"
    >
      <ChartContainer
        config={PRODUCT_CONFIG}
        className="aspect-auto w-full"
        style={{ height: Math.max(220, products.length * 44 + 40) }}
      >
        <BarChart data={products} layout="vertical" margin={{ left: 4, right: 12 }}>
          <CartesianGrid horizontal={false} />
          <YAxis dataKey="product_name" type="category" width={150} tickFormatter={(v: string) => (v.length > 22 ? `${v.slice(0, 21)}…` : v)} {...AXIS} />
          <XAxis type="number" tickFormatter={formatCompactNumber} {...AXIS} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="units_ordered" fill="var(--color-units_ordered)" radius={[0, 4, 4, 0]} barSize={12} />
          <Bar dataKey="units_shipped" fill="var(--color-units_shipped)" radius={[0, 4, 4, 0]} barSize={12} />
        </BarChart>
      </ChartContainer>
    </ChartCard>
  );
}

const EXCEPTION_CONFIG: ChartConfig = {
  open_count: { label: "Open", color: "var(--chart-4)" },
};

export function OpenExceptionsCard({ counts }: { counts: ExceptionCountByCategory[] }) {
  const data = counts.map((c) => ({
    ...c,
    name: EXCEPTION_CATEGORY_LABEL[c.category] ?? c.category,
  }));
  return (
    <ChartCard
      title="Open exceptions"
      description="Problems flagged and not yet cleared, by category"
      isEmpty={counts.length === 0}
      emptyMessage="No open exceptions right now."
      className="xl:col-span-6"
    >
      <ChartContainer
        config={EXCEPTION_CONFIG}
        className="aspect-auto w-full"
        style={{ height: Math.max(180, data.length * 52 + 40) }}
      >
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 16 }}>
          <CartesianGrid horizontal={false} />
          <YAxis dataKey="name" type="category" width={150} {...AXIS} />
          <XAxis type="number" allowDecimals={false} {...AXIS} />
          <ChartTooltip content={<ChartTooltipContent hideLabel />} />
          <Bar dataKey="open_count" fill="var(--color-open_count)" radius={[0, 4, 4, 0]} barSize={20} />
        </BarChart>
      </ChartContainer>
    </ChartCard>
  );
}
