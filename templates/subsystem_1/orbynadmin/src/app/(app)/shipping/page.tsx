import { IconTruck } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export default function ShippingPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Shipping"
        description="Shipment tracking and OTIF drill-down."
      />
      <EmptyState
        icon={IconTruck}
        title="No shipments yet"
        description="Shipment tracking appears here once this view is wired to the real API layer."
      />
    </div>
  );
}
