import { PageHeader } from "@/components/page-header";
import { ShipmentsTable } from "@/components/shipments-table";
import { listShipments } from "@/lib/dashboard-api";
import type { Shipment } from "@/types/dashboard";

export default async function ShippingPage() {
  const response = await listShipments();
  const shipments: Shipment[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title="Shipping" description="Shipment tracking and OTIF drill-down." />
      <ShipmentsTable shipments={shipments} />
    </div>
  );
}
