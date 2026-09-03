import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { PurchaseOrdersTable } from "@/components/purchase-orders-table";
import { Button } from "@/components/ui/button";
import { listPurchaseOrders } from "@/lib/dashboard-api";
import type { PurchaseOrderSummary } from "@/types/dashboard";

export default async function OrdersPage() {
  const response = await listPurchaseOrders();
  const purchaseOrders: PurchaseOrderSummary[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Purchase Orders"
        description="Purchase and sales orders (generalized from the same table pattern)."
      >
        <Button variant="outline" size="sm" asChild>
          <Link href="/orders/sales">Sales orders</Link>
        </Button>
      </PageHeader>
      <PurchaseOrdersTable purchaseOrders={purchaseOrders} />
    </div>
  );
}
