import { Card, CardContent } from "@/components/ui/card"

export interface ExecutiveSummary {
  kpis: {
    simulation_date: string;
    otif_pct: string | null;
    fill_rate_pct: string | null;
    order_cycle_time_days: string | null;
    perfect_order_rate_pct: string | null;
  } | null;
  open_exception_counts: { category: string; open_count: number }[];
}

function formatValue(value: string | null, suffix: string): string {
  if (value === null) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(1)}${suffix}` : "—";
}

function categoryLabel(category: string): string {
  const spaced = category.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// Unit 39 (PRD 6.1): the company's current position, straight from the latest
// KPI snapshot and the open exception flags - nothing derived or estimated here.
export function CompanyStatus({ summary }: { summary: ExecutiveSummary | null }) {
  if (summary === null || summary.kpis === null) {
    return (
      <div className="rounded-lg border py-10 text-center text-sm text-muted-foreground">
        No KPI data yet. Company status appears after the simulation&apos;s first daily run.
      </div>
    );
  }

  const tiles = [
    { label: "OTIF", value: formatValue(summary.kpis.otif_pct, "%") },
    { label: "Fill rate", value: formatValue(summary.kpis.fill_rate_pct, "%") },
    { label: "Order cycle time", value: formatValue(summary.kpis.order_cycle_time_days, " days") },
    { label: "Perfect order rate", value: formatValue(summary.kpis.perfect_order_rate_pct, "%") },
  ];
  const openTotal = summary.open_exception_counts.reduce((sum, row) => sum + row.open_count, 0);

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">As of {summary.kpis.simulation_date}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((tile) => (
          <Card key={tile.label}>
            <CardContent className="space-y-1 pt-6">
              <p className="text-xs text-muted-foreground">{tile.label}</p>
              <p className="text-2xl font-semibold tabular-nums">{tile.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="rounded-lg border px-4 py-3 text-sm">
        <p className="font-medium">
          {openTotal === 0 ? "No open exceptions" : `${openTotal} open exception${openTotal === 1 ? "" : "s"}`}
        </p>
        {openTotal > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">
            {summary.open_exception_counts
              .map((row) => `${categoryLabel(row.category)}: ${row.open_count}`)
              .join(" · ")}
          </p>
        )}
      </div>
    </div>
  );
}
