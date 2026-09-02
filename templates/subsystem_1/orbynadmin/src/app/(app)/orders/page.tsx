import { IconShoppingCart } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export default function OrdersPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Orders"
        description="Purchase and sales orders (generalized from the same table pattern)."
      />
      <EmptyState
        icon={IconShoppingCart}
        title="No orders yet"
        description="Orders appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
