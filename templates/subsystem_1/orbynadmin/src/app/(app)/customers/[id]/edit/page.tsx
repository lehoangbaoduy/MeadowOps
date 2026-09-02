import Link from "next/link";
import { IconArrowLeft, IconUser } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export const metadata = { title: "Edit customer" };

export default function EditCustomerPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Edit customer">
        <Button variant="outline" size="sm" asChild>
          <Link href="/customers">
            <IconArrowLeft className="size-4" /> Back to customers
          </Link>
        </Button>
      </PageHeader>
      <EmptyState
        icon={IconUser}
        title="Customer editing not available yet"
        description="This form appears here once customers are wired to the real API layer."
      />
    </div>
  );
}
