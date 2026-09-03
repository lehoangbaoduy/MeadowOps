"use client";

import * as React from "react";
import Link from "next/link";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/dashboard-format";
import { EXCEPTION_CATEGORY_LABEL, type ExceptionFlag } from "@/types/dashboard";

function entityLabel(flag: ExceptionFlag): string {
  if (flag.purchase_order_id) return flag.purchase_order_id.slice(0, 8);
  if (flag.shipment_id) return flag.shipment_id.slice(0, 8);
  if (flag.product_id && flag.warehouse_id) return `${flag.product_id} @ ${flag.warehouse_id}`;
  return "—";
}

/** Unit 16 (MEADOWOPS-API-003): Data-Quality view — the general exception
 * queue S1-FR-4 flags feed into (SR-1..SR-4 conflicting-source/bad-data
 * cases are Unit 17's own scope, not reimplemented here). */
export function ExceptionsTable({ exceptions }: { exceptions: ExceptionFlag[] }) {
  const columns = React.useMemo<ColumnDef<ExceptionFlag>[]>(
    () => [
      {
        accessorKey: "category",
        header: ({ column }) => <SortableHeader column={column} title="Category" />,
        cell: ({ row }) => EXCEPTION_CATEGORY_LABEL[row.original.category] ?? row.original.category,
      },
      {
        id: "entity",
        header: "Entity",
        cell: ({ row }) => (
          <Link href={`/reports/${row.original.id}`} className="font-medium hover:underline">
            {entityLabel(row.original)}
          </Link>
        ),
      },
      {
        accessorKey: "measured_value",
        header: "Measured",
        cell: ({ row }) => row.original.measured_value ?? "—",
      },
      {
        accessorKey: "threshold_value",
        header: "Threshold",
      },
      {
        accessorKey: "first_detected_simulation_date",
        header: ({ column }) => <SortableHeader column={column} title="First Detected" />,
        cell: ({ row }) => formatDate(row.original.first_detected_simulation_date),
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) =>
          row.original.resolved_at ? (
            <Badge variant="secondary">Resolved</Badge>
          ) : (
            <Badge variant="destructive">Open</Badge>
          ),
      },
    ],
    []
  );

  return <DataTable columns={columns} data={exceptions} />;
}
