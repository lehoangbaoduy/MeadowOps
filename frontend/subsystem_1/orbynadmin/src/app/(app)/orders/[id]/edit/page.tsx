import Link from "next/link";
import { IconArrowLeft, IconReceipt } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export const metadata = { title: "Edit order" };

export default function EditOrderPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Edit order">
        <Button variant="outline" size="sm" asChild>
          <Link href="/orders">
            <IconArrowLeft className="size-4" /> Back to orders
          </Link>
        </Button>
      </PageHeader>
      <EmptyState
        icon={IconReceipt}
        title="Order editing not available yet"
        description="This form appears here once orders are wired to the real API layer."
      />
    </div>
  );
}
