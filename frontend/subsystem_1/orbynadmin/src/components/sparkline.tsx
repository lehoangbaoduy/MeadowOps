"use client";

import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";

/**
 * Unit 16 follow-up: a compact per-KPI-card trend, not a full axis-and-legend
 * chart — the Overview page's job is "what is it right now," so this only
 * needs to answer "roughly which way has it been moving," not carry its own
 * scale/labels. Kept a plain array of numbers in, not the ExecutiveKpi[]
 * shape, so the KPI card doesn't need to know the trend endpoint exists.
 */
export function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) {
    return null;
  }
  const points = data.map((value, index) => ({ index, value }));
  // A flat/constant series (e.g. OTIF pinned at 100%) gives Recharts a
  // zero-height domain, which it renders as a filled block instead of a
  // line — pad the domain so a flat run still reads as a flat line.
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pad = max - min === 0 ? Math.max(Math.abs(max) * 0.1, 1) : (max - min) * 0.15;

  return (
    <div className="h-8 w-20 shrink-0" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 2, right: 1, bottom: 0, left: 1 }}>
          <YAxis hide domain={[min - pad, max + pad]} />
          <defs>
            <linearGradient id={`sparkline-fill-${color.replace(/[^a-zA-Z0-9]/g, "")}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            dataKey="value"
            type="monotone"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#sparkline-fill-${color.replace(/[^a-zA-Z0-9]/g, "")})`}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
