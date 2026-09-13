import { IconActivity } from "@tabler/icons-react";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { DecisionsTable } from "@/components/decisions-table";
import { listDecisions } from "@/lib/ledger-api";
import type { DecisionEvent } from "@/types/ledger";

export default async function ActivityPage() {
  const response = await listDecisions();
  const decisions: DecisionEvent[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description="Decision & Event Ledger — a timestamped log of decisions and events."
      />
      {decisions.length === 0 ? (
        <EmptyState
          icon={IconActivity}
          title="No activity yet"
          description="Ledger entries appear here once a decision is proposed."
        />
      ) : (
        <DecisionsTable decisions={decisions} />
      )}
    </div>
  );
}
