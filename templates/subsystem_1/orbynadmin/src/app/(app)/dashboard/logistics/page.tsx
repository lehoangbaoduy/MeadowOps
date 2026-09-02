import {
  IconCalendarStats,
  IconCircleCheck,
  IconClockHour4,
  IconPackageExport,
  IconTruckDelivery,
} from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { KpiCard } from "@/components/kpi-card";

// PRD Appendix A — the five core KPIs, in the same order as Unit 10's
// backend/sql/kpi/ files (otif, fill_rate, days_of_supply, order_cycle_time,
// perfect_order_rate). Unit 16 (Phase 2, now scoped full-stack per DD-17/B7)
// wires each card's value; this unit only builds the slot each one fills.
const KPI_CARDS = [
  { icon: IconTruckDelivery, label: "OTIF", unit: "%" },
  { icon: IconPackageExport, label: "Fill Rate", unit: "%" },
  { icon: IconCalendarStats, label: "Days of Supply", unit: "days" },
  { icon: IconClockHour4, label: "Order Cycle Time", unit: "days" },
  { icon: IconCircleCheck, label: "Perfect Order Rate", unit: "%" },
] as const;

export default function LogisticsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description="OTIF, fill rate and days-of-supply across the network."
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {KPI_CARDS.map((kpi) => (
          <KpiCard key={kpi.label} icon={kpi.icon} label={kpi.label} unit={kpi.unit} />
        ))}
      </div>
    </div>
  );
}
