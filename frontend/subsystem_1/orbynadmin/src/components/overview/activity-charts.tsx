"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Label,
  Line,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  formatCompactCurrency,
  formatCompactNumber,
  formatShortDate,
} from "@/lib/dashboard-format";
import type {
  ExecutiveKpi,
  OverviewDailyActivity,
  OverviewShipmentBreakdown,
} from "@/types/dashboard";
import { ChartCard } from "./chart-card";

// Tooltip labels arrive as ReactNode; ours are always ISO date strings.
const tooltipDate = (label: unknown): string => formatShortDate(String(label));

const AXIS = { tickLine: false, axisLine: false, tickMargin: 8 } as const;

// ---- KPI trend --------------------------------------------------------

const KPI_CONFIG: ChartConfig = {
  otif_pct: { label: "OTIF %", color: "var(--chart-1)" },
  fill_rate_pct: { label: "Fill rate %", color: "var(--chart-2)" },
  perfect_order_rate_pct: { label: "Perfect order %", color: "var(--chart-3)" },
};

const toNumber = (value: string | null): number | null => (value == null ? null : Number(value));

export function KpiTrendCard({ rows }: { rows: Omit<ExecutiveKpi, "computed_at">[] }) {
  const data = rows.map((row) => ({
    simulation_date: row.simulation_date,
    otif_pct: toNumber(row.otif_pct),
    fill_rate_pct: toNumber(row.fill_rate_pct),
    perfect_order_rate_pct: toNumber(row.perfect_order_rate_pct),
  }));
  return (
    <ChartCard
      title="Service level trend"
      description="Running OTIF, fill rate and perfect-order rate, as recorded each day"
      isEmpty={data.length < 2}
      emptyMessage="A trend needs at least two daily KPI readings."
      className="xl:col-span-8"
    >
      <ChartContainer config={KPI_CONFIG} className="aspect-auto h-[300px] w-full">
        <AreaChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
          <defs>
            {Object.keys(KPI_CONFIG).map((key) => (
              <linearGradient key={key} id={`ov-kpi-${key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={`var(--color-${key})`} stopOpacity={0.3} />
                <stop offset="95%" stopColor={`var(--color-${key})`} stopOpacity={0.02} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="simulation_date" tickFormatter={formatShortDate} minTickGap={24} {...AXIS} />
          <YAxis domain={[0, 100]} width={48} unit="%" {...AXIS} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipDate} />} />
          <ChartLegend content={<ChartLegendContent />} />
          {Object.keys(KPI_CONFIG).map((key) => (
            <Area
              key={key}
              dataKey={key}
              type="monotone"
              stroke={`var(--color-${key})`}
              fill={`url(#ov-kpi-${key})`}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---- Delivery performance donut ---------------------------------------

const DELIVERY_CONFIG: ChartConfig = {
  delivered_on_time: { label: "Delivered on time", color: "var(--chart-2)" },
  delivered_late: { label: "Delivered late", color: "var(--chart-4)" },
  in_progress: { label: "In progress", color: "var(--chart-1)" },
  exception: { label: "Exception", color: "var(--chart-3)" },
};

export function ShipmentOutcomeCard({ breakdown }: { breakdown: OverviewShipmentBreakdown }) {
  const data = (Object.keys(DELIVERY_CONFIG) as (keyof OverviewShipmentBreakdown)[])
    .map((key) => ({ key, label: DELIVERY_CONFIG[key].label as string, value: breakdown[key], fill: `var(--color-${key})` }))
    .filter((slice) => slice.value > 0);
  const total = data.reduce((sum, slice) => sum + slice.value, 0);
  return (
    <ChartCard
      title="Shipment outcomes"
      description="Shipments dispatched in this window"
      isEmpty={total === 0}
      emptyMessage="No shipments dispatched in this window."
      className="xl:col-span-4"
    >
      <ChartContainer config={DELIVERY_CONFIG} className="mx-auto aspect-square h-[300px]">
        <PieChart>
          <ChartTooltip content={<ChartTooltipContent hideLabel nameKey="key" />} />
          <Pie data={data} dataKey="value" nameKey="key" innerRadius={72} outerRadius={110} strokeWidth={3} paddingAngle={2}>
            <Label
              content={({ viewBox }) =>
                viewBox && "cx" in viewBox && "cy" in viewBox ? (
                  <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                    <tspan x={viewBox.cx} y={viewBox.cy} className="fill-foreground text-3xl font-semibold">
                      {total}
                    </tspan>
                    <tspan x={viewBox.cx} y={(viewBox.cy ?? 0) + 22} className="fill-muted-foreground text-xs">
                      shipments
                    </tspan>
                  </text>
                ) : null
              }
            />
          </Pie>
          <ChartLegend content={<ChartLegendContent nameKey="key" />} />
        </PieChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---- Orders & demand per day -----------------------------------------

const ACTIVITY_CONFIG: ChartConfig = {
  orders_placed: { label: "Orders placed", color: "var(--chart-1)" },
  order_value: { label: "Order value", color: "var(--chart-5)" },
};

export function OrderActivityCard({ days }: { days: OverviewDailyActivity[] }) {
  const data = days.map((day) => ({ ...day, order_value: Number(day.order_value) }));
  return (
    <ChartCard
      title="Orders and demand"
      description="Sales orders placed per day, with the value of what was ordered"
      isEmpty={data.every((day) => day.orders_placed === 0)}
      emptyMessage="No sales orders were placed in this window."
      className="xl:col-span-7"
    >
      <ChartContainer config={ACTIVITY_CONFIG} className="aspect-auto h-[280px] w-full">
        <ComposedChart data={data} margin={{ left: 4, right: 4, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="simulation_date" tickFormatter={formatShortDate} minTickGap={24} {...AXIS} />
          <YAxis yAxisId="orders" allowDecimals={false} width={32} {...AXIS} />
          <YAxis yAxisId="value" orientation="right" width={52} tickFormatter={formatCompactCurrency} {...AXIS} />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={tooltipDate}
                formatter={(value, name) => (
                  <span className="flex w-full justify-between gap-3">
                    <span className="text-muted-foreground">{ACTIVITY_CONFIG[String(name)]?.label}</span>
                    <span className="font-mono font-medium tabular-nums">
                      {name === "order_value" ? formatCompactCurrency(Number(value)) : value}
                    </span>
                  </span>
                )}
              />
            }
          />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar yAxisId="orders" dataKey="orders_placed" fill="var(--color-orders_placed)" radius={[4, 4, 0, 0]} maxBarSize={28} />
          <Line yAxisId="value" dataKey="order_value" type="monotone" stroke="var(--color-order_value)" strokeWidth={2} dot={false} />
        </ComposedChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---- Deliveries per day ----------------------------------------------

const DELIVERIES_CONFIG: ChartConfig = {
  delivered_on_time: { label: "On time", color: "var(--chart-2)" },
  delivered_late: { label: "Late", color: "var(--chart-4)" },
};

export function DeliveriesCard({ days }: { days: OverviewDailyActivity[] }) {
  return (
    <ChartCard
      title="Deliveries per day"
      description="Shipments delivered, split by whether they met the promised date"
      isEmpty={days.every((day) => day.delivered_on_time + day.delivered_late === 0)}
      emptyMessage="No deliveries completed in this window."
      className="xl:col-span-5"
    >
      <ChartContainer config={DELIVERIES_CONFIG} className="aspect-auto h-[280px] w-full">
        <BarChart data={days} margin={{ left: 4, right: 4, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="simulation_date" tickFormatter={formatShortDate} minTickGap={24} {...AXIS} />
          <YAxis allowDecimals={false} width={28} {...AXIS} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipDate} />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="delivered_on_time" stackId="d" fill="var(--color-delivered_on_time)" maxBarSize={28} />
          <Bar dataKey="delivered_late" stackId="d" fill="var(--color-delivered_late)" radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---- Order status donut ----------------------------------------------

const STATUS_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

export function OrderStatusCard({ statuses }: { statuses: { label: string; count: number }[] }) {
  const config: ChartConfig = Object.fromEntries(
    statuses.map((s, i) => [s.label, { label: s.label.replace(/_/g, " "), color: STATUS_COLORS[i % STATUS_COLORS.length] }])
  );
  const data = statuses.map((s) => ({ ...s, fill: `var(--color-${s.label})` }));
  const total = statuses.reduce((sum, s) => sum + s.count, 0);
  return (
    <ChartCard
      title="Where orders stand"
      description="Sales orders placed in this window, by current status"
      isEmpty={total === 0}
      emptyMessage="No sales orders were placed in this window."
      className="xl:col-span-4"
    >
      <ChartContainer config={config} className="mx-auto aspect-square h-[280px]">
        <PieChart>
          <ChartTooltip content={<ChartTooltipContent hideLabel nameKey="label" />} />
          <Pie data={data} dataKey="count" nameKey="label" innerRadius={64} outerRadius={100} strokeWidth={3} paddingAngle={2}>
            <Label
              content={({ viewBox }) =>
                viewBox && "cx" in viewBox && "cy" in viewBox ? (
                  <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                    <tspan x={viewBox.cx} y={viewBox.cy} className="fill-foreground text-3xl font-semibold">
                      {formatCompactNumber(total)}
                    </tspan>
                    <tspan x={viewBox.cx} y={(viewBox.cy ?? 0) + 22} className="fill-muted-foreground text-xs">
                      orders
                    </tspan>
                  </text>
                ) : null
              }
            />
          </Pie>
          <ChartLegend content={<ChartLegendContent nameKey="label" />} />
        </PieChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---- New exceptions per day ------------------------------------------

const EXCEPTION_DAY_CONFIG: ChartConfig = {
  count: { label: "New exceptions", color: "var(--chart-4)" },
};

export function NewExceptionsCard({ days }: { days: { simulation_date: string; count: number }[] }) {
  return (
    <ChartCard
      title="Exceptions detected per day"
      description="Newly flagged problems, whether or not they have since cleared"
      isEmpty={days.every((day) => day.count === 0)}
      emptyMessage="No new exceptions were detected in this window."
      className="xl:col-span-5"
    >
      <ChartContainer config={EXCEPTION_DAY_CONFIG} className="aspect-auto h-[240px] w-full">
        <AreaChart data={days} margin={{ left: 4, right: 12, top: 8 }}>
          <defs>
            <linearGradient id="ov-exc-day" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-count)" stopOpacity={0.35} />
              <stop offset="95%" stopColor="var(--color-count)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="simulation_date" tickFormatter={formatShortDate} minTickGap={24} {...AXIS} />
          <YAxis allowDecimals={false} width={28} {...AXIS} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipDate} />} />
          <Area dataKey="count" type="stepAfter" stroke="var(--color-count)" fill="url(#ov-exc-day)" strokeWidth={2} dot={false} />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}
