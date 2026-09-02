import Link from "next/link";
import { IconArrowLeft, IconUser } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export const metadata = { title: "Customer" };

export default function CustomerDetailPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Customer">
        <Button variant="outline" size="sm" asChild>
          <Link href="/customers">
            <IconArrowLeft className="size-4" /> Back to customers
          </Link>
        </Button>
      </PageHeader>
      <EmptyState
        icon={IconUser}
        title="Customer detail not available yet"
        description="Customer records appear here once this view is wired to the real API layer."
      />
    </div>
  );
}
