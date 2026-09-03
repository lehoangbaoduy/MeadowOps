import { PageHeader } from "@/components/page-header";
import { SupplierPerformanceTable } from "@/components/supplier-performance-table";
import { listSupplierPerformance } from "@/lib/dashboard-api";
import type { SupplierPerformance } from "@/types/dashboard";

export default async function SuppliersPage() {
  const response = await listSupplierPerformance();
  const suppliers: SupplierPerformance[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title="Suppliers" description="Purchase-order performance and at-risk exposure by supplier." />
      <SupplierPerformanceTable suppliers={suppliers} />
    </div>
  );
}
