import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { SalesOrdersTable } from "@/components/sales-orders-table";
import { Button } from "@/components/ui/button";
import { listSalesOrders } from "@/lib/dashboard-api";
import type { SalesOrderSummary } from "@/types/dashboard";

export default async function SalesOrdersPage() {
  const response = await listSalesOrders();
  const salesOrders: SalesOrderSummary[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title="Sales Orders" description="Customer orders and their fulfillment status.">
        <Button variant="outline" size="sm" asChild>
          <Link href="/orders">Purchase orders</Link>
        </Button>
      </PageHeader>
      <SalesOrdersTable salesOrders={salesOrders} />
    </div>
  );
}
