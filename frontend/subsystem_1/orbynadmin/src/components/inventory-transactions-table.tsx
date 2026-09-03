"use client";

import * as React from "react";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/dashboard-format";
import type { InventoryTransaction } from "@/types/dashboard";

const TYPE_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  receipt: "default",
  shipment: "secondary",
  adjustment: "outline",
  transfer_in: "default",
  transfer_out: "secondary",
  cycle_count: "outline",
};

export function InventoryTransactionsTable({ transactions }: { transactions: InventoryTransaction[] }) {
  const columns = React.useMemo<ColumnDef<InventoryTransaction>[]>(
    () => [
      {
        accessorKey: "transaction_at",
        header: ({ column }) => <SortableHeader column={column} title="When" />,
        cell: ({ row }) => formatDateTime(row.original.transaction_at),
      },
      {
        accessorKey: "transaction_type",
        header: "Type",
        cell: ({ row }) => (
          <Badge variant={TYPE_VARIANT[row.original.transaction_type] ?? "outline"}>
            {row.original.transaction_type.replace("_", " ")}
          </Badge>
        ),
      },
      {
        accessorKey: "quantity_delta",
        header: ({ column }) => <SortableHeader column={column} title="Quantity" />,
        cell: ({ row }) => (
          <span className={row.original.quantity_delta < 0 ? "text-destructive" : ""}>
            {row.original.quantity_delta > 0 ? "+" : ""}
            {row.original.quantity_delta}
          </span>
        ),
      },
      {
        accessorKey: "reference_type",
        header: "Reference",
        cell: ({ row }) => row.original.reference_type ?? "—",
      },
      {
        accessorKey: "source_system",
        header: "Source",
      },
    ],
    []
  );

  return <DataTable columns={columns} data={transactions} />;
}
