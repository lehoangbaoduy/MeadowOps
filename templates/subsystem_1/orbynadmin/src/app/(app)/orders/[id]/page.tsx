import Link from "next/link";
import { IconArrowLeft, IconReceipt } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export const metadata = { title: "Order" };

export default function OrderDetailPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Order">
        <Button variant="outline" size="sm" asChild>
          <Link href="/orders">
            <IconArrowLeft className="size-4" /> Back to orders
          </Link>
        </Button>
      </PageHeader>
      <EmptyState
        icon={IconReceipt}
        title="Order detail not available yet"
        description="Order records appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
