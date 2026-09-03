import { PageHeader } from "@/components/page-header";
import { InventoryTable } from "@/components/inventory-table";
import { listInventoryPositions } from "@/lib/dashboard-api";
import type { InventoryPosition } from "@/types/dashboard";

export default async function InventoryPage() {
  const response = await listInventoryPositions();
  const positions: InventoryPosition[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title="Inventory" description="Inventory position and snapshot across warehouses." />
      <InventoryTable positions={positions} />
    </div>
  );
}
