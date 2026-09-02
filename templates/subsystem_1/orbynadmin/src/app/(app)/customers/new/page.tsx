import Link from "next/link";
import { IconArrowLeft, IconUser } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export const metadata = { title: "New customer" };

export default function NewCustomerPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="New customer">
        <Button variant="outline" size="sm" asChild>
          <Link href="/customers">
            <IconArrowLeft className="size-4" /> Back to customers
          </Link>
        </Button>
      </PageHeader>
      <EmptyState
        icon={IconUser}
        title="Customer creation not available yet"
        description="This form appears here once customers are wired to the real API layer."
      />
    </div>
  );
}
