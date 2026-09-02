import type { TablerIcon } from "@tabler/icons-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * A single KPI slot on the control-tower dashboard (Unit 12b/MEADOWOPS-UI-002,
 * PRD Appendix A). Renders the card's real structure — label, unit, an empty
 * "—" value — with no computed figure, since the KPI engine (Unit 14/16)
 * doesn't exist yet. Deliberately not "0%"/"0 days": a zero could be
 * mistaken for a real calculated value, which the zero-fabricated-data rule
 * (PRD 1.6/Appendix D) rules out just as much as a fake nonzero one.
 */
type KpiCardProps = {
  icon: TablerIcon;
  label: string;
  unit: string;
};

export function KpiCard({ icon: Icon, label, unit }: KpiCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <Icon className="size-4" />
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold tabular-nums">
          {/* aria-hidden + sr-only text: a bare <span>'s implicit role
              (generic) is on ARIA's "name prohibited" list, so aria-label
              alone isn't spec-guaranteed to produce an accessible name here
              (security review of this unit) */}
          <span aria-hidden="true">—</span>
          <span className="sr-only">No data yet</span>
          <span className="ml-1 text-sm font-normal text-muted-foreground">
            {unit}
          </span>
        </p>
      </CardContent>
    </Card>
  );
}
