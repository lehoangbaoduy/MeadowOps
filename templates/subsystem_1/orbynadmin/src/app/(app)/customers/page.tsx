import { PageHeader } from "@/components/page-header";
import { CustomersTable, type CustomerRow } from "@/components/customers-table";
import { listMasterData } from "@/lib/admin-api";

export default async function CustomersPage() {
  const response = await listMasterData("customers");
  const customers: CustomerRow[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader title="Customers" description="Customer master data." />
      <CustomersTable customers={customers} />
    </div>
  );
}
