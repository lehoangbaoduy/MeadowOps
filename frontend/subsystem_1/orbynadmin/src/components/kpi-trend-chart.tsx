"use client";

import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { ExecutiveKpi } from "@/types/dashboard";

/**
 * Unit 16: Appendix D's "Analytics dashboard -> KPI trend drill-down"
 * ("Charting backbone (Recharts) reused as-is"). Renders the percentage
 * KPIs on one 0-100 axis — order_cycle_time_days is a day count on a very
 * different scale, plotted separately below by the page rather than
 * squeezed onto the same axis.
 */
const CHART_CONFIG: ChartConfig = {
  otif_pct: { label: "OTIF %", color: "var(--chart-1)" },
  fill_rate_pct: { label: "Fill Rate %", color: "var(--chart-2)" },
  perfect_order_rate_pct: { label: "Perfect Order %", color: "var(--chart-3)" },
};

export function KpiTrendChart({ rows }: { rows: ExecutiveKpi[] }) {
  const data = rows.map((r) => ({
    simulation_date: r.simulation_date,
    otif_pct: r.otif_pct == null ? null : Number(r.otif_pct),
    fill_rate_pct: r.fill_rate_pct == null ? null : Number(r.fill_rate_pct),
    perfect_order_rate_pct: r.perfect_order_rate_pct == null ? null : Number(r.perfect_order_rate_pct),
  }));

  return (
    <ChartContainer config={CHART_CONFIG} className="aspect-auto h-[320px] w-full">
      <AreaChart data={data} margin={{ left: 12, right: 12, top: 12 }}>
        <defs>
          {Object.keys(CHART_CONFIG).map((key) => (
            <linearGradient key={key} id={`trend-fill-${key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={`var(--color-${key})`} stopOpacity={0.28} />
              <stop offset="95%" stopColor={`var(--color-${key})`} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="simulation_date" tickLine={false} axisLine={false} tickMargin={8} />
        <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tickMargin={8} width={36} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Area
          dataKey="otif_pct"
          type="monotone"
          stroke="var(--color-otif_pct)"
          fill="url(#trend-fill-otif_pct)"
          strokeWidth={2}
          dot={{ r: 3, strokeWidth: 0, fill: "var(--color-otif_pct)" }}
          activeDot={{ r: 5 }}
          connectNulls
        />
        <Area
          dataKey="fill_rate_pct"
          type="monotone"
          stroke="var(--color-fill_rate_pct)"
          fill="url(#trend-fill-fill_rate_pct)"
          strokeWidth={2}
          dot={{ r: 3, strokeWidth: 0, fill: "var(--color-fill_rate_pct)" }}
          activeDot={{ r: 5 }}
          connectNulls
        />
        <Area
          dataKey="perfect_order_rate_pct"
          type="monotone"
          stroke="var(--color-perfect_order_rate_pct)"
          fill="url(#trend-fill-perfect_order_rate_pct)"
          strokeWidth={2}
          dot={{ r: 3, strokeWidth: 0, fill: "var(--color-perfect_order_rate_pct)" }}
          activeDot={{ r: 5 }}
          connectNulls
        />
      </AreaChart>
    </ChartContainer>
  );
}
