import Link from "next/link";
import { notFound } from "next/navigation";
import { IconArrowLeft } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { InventoryTransactionsTable } from "@/components/inventory-transactions-table";
import { listInventoryTransactions } from "@/lib/dashboard-api";
import type { InventoryTransaction } from "@/types/dashboard";

export default async function InventoryTransactionsPage({
  params,
}: {
  params: Promise<{ productId: string; warehouseId: string }>;
}) {
  const { productId, warehouseId } = await params;
  const response = await listInventoryTransactions(productId, warehouseId);
  if (response.status === 404) {
    notFound();
  }
  const transactions: InventoryTransaction[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title={`${productId} @ ${warehouseId}`} description="Inventory transaction ledger.">
        <Button variant="outline" size="sm" asChild>
          <Link href="/inventory">
            <IconArrowLeft className="size-4" /> Back to inventory
          </Link>
        </Button>
      </PageHeader>
      <InventoryTransactionsTable transactions={transactions} />
    </div>
  );
}
