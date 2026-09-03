import Link from "next/link";
import { notFound } from "next/navigation";
import { IconArrowLeft } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { PurchaseOrdersTable } from "@/components/purchase-orders-table";
import { listSupplierPurchaseOrders } from "@/lib/dashboard-api";
import type { PurchaseOrderSummary } from "@/types/dashboard";

export default async function SupplierDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await listSupplierPurchaseOrders(id);
  if (response.status === 404) {
    notFound();
  }
  const purchaseOrders: PurchaseOrderSummary[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title={id} description="Purchase orders for this supplier.">
        <Button variant="outline" size="sm" asChild>
          <Link href="/suppliers">
            <IconArrowLeft className="size-4" /> Back to suppliers
          </Link>
        </Button>
      </PageHeader>
      <PurchaseOrdersTable purchaseOrders={purchaseOrders} />
    </div>
  );
}
