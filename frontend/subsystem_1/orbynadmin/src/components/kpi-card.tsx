import type { TablerIcon } from "@tabler/icons-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkline } from "@/components/sparkline";

/**
 * A single KPI slot on the control-tower dashboard (Unit 12b/MEADOWOPS-UI-002,
 * PRD Appendix A). `value` is undefined/null until a real figure exists
 * (Unit 16 wires it from GET /api/v1/dashboard/executive, itself null
 * until the scheduler's first tick has ever run) — renders the same "—"
 * placeholder Unit 12b originally shipped rather than a fabricated "0%":
 * a zero could be mistaken for a real calculated value, which the
 * zero-fabricated-data rule (PRD 1.6/Appendix D) rules out just as much as
 * a fake nonzero one.
 */
type KpiCardProps = {
  icon: TablerIcon;
  label: string;
  unit: string;
  value?: string | null;
  trend?: number[];
  trendColor?: string;
};

export function KpiCard({ icon: Icon, label, unit, value, trend, trendColor }: KpiCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <Icon className="size-4" />
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex items-end justify-between gap-3">
        <p className="text-2xl font-semibold tabular-nums">
          {value != null ? (
            value
          ) : (
            <>
              {/* aria-hidden + sr-only text: a bare <span>'s implicit role
                  (generic) is on ARIA's "name prohibited" list, so
                  aria-label alone isn't spec-guaranteed to produce an
                  accessible name here (security review of Unit 12b) */}
              <span aria-hidden="true">—</span>
              <span className="sr-only">No data yet</span>
            </>
          )}
          <span className="ml-1 text-sm font-normal text-muted-foreground">
            {unit}
          </span>
        </p>
        {trend && trend.length >= 2 && (
          <Sparkline data={trend} color={trendColor ?? "var(--chart-1)"} />
        )}
      </CardContent>
    </Card>
  );
}
