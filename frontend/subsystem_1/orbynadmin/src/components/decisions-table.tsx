"use client";

import * as React from "react";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { DecisionActions } from "@/components/decision-actions";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/dashboard-format";
import { DECISION_STATUS_LABEL, type DecisionEvent, type DecisionEventStatus } from "@/types/ledger";

const STATUS_BADGE_VARIANT: Record<DecisionEventStatus, "default" | "secondary" | "destructive" | "outline"> = {
  proposed: "outline",
  clarification_requested: "outline",
  accepted: "default",
  rejected: "destructive",
  implemented: "default",
  partially_implemented: "default",
  outcome_observed: "secondary",
  stale: "destructive",
};

/** Unit 24 (MEADOWOPS-DOM-018, PRD 4.4/Appendix D.1): the Decision & Event
 * Ledger's Activity view - a timestamped log (Appendix D.1: "Timestamped
 * log pattern fits directly") plus, since Unit 34, an Actions column
 * driving the decision lifecycle (request-clarification/accept/reject/
 * resubmit/implement/partially-implement/outcome) via app.api.ledger's
 * require_admin write routes - DecisionActions derives which buttons to
 * show from `status` alone, same convention as Subsystem 2's
 * ScenarioActions.availableActions. */
export function DecisionsTable({ decisions }: { decisions: DecisionEvent[] }) {
  const columns = React.useMemo<ColumnDef<DecisionEvent>[]>(
    () => [
      {
        accessorKey: "title",
        header: ({ column }) => <SortableHeader column={column} title="Title" />,
      },
      {
        id: "entity",
        header: "Entity",
        cell: ({ row }) => `${row.original.entity_type} · ${row.original.entity_id}`,
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) => (
          <Badge variant={STATUS_BADGE_VARIANT[row.original.status]}>
            {DECISION_STATUS_LABEL[row.original.status]}
          </Badge>
        ),
      },
      {
        accessorKey: "proposed_at",
        header: ({ column }) => <SortableHeader column={column} title="Proposed" />,
        cell: ({ row }) => formatDateTime(row.original.proposed_at),
      },
      {
        id: "decided_by",
        header: "Decided By",
        cell: ({ row }) => row.original.decided_by ?? "—",
      },
      {
        id: "outcome",
        header: "Outcome",
        cell: ({ row }) => row.original.outcome ?? "—",
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => <DecisionActions decision={row.original} />,
      },
    ],
    []
  );

  return <DataTable columns={columns} data={decisions} />;
}
