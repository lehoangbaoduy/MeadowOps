import { IconPackages } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export default function InventoryPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Inventory"
        description="Inventory position and snapshot across warehouses."
      />
      <EmptyState
        icon={IconPackages}
        title="No inventory data yet"
        description="Stock positions appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
