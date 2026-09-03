"use client";

import * as React from "react";
import Link from "next/link";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/dashboard-format";
import type { PurchaseOrderSummary } from "@/types/dashboard";

const STATUS_LABEL: Record<PurchaseOrderSummary["status"], string> = {
  draft: "Draft",
  submitted: "Submitted",
  confirmed: "Confirmed",
  partially_received: "Partially received",
  received: "Received",
  cancelled: "Cancelled",
};

/** Unit 16: shared by /orders (all POs) and /suppliers/[id] (one supplier's POs). */
export function PurchaseOrdersTable({ purchaseOrders }: { purchaseOrders: PurchaseOrderSummary[] }) {
  const columns = React.useMemo<ColumnDef<PurchaseOrderSummary>[]>(
    () => [
      {
        accessorKey: "po_number",
        header: ({ column }) => <SortableHeader column={column} title="PO Number" />,
        cell: ({ row }) => (
          <Link href={`/orders/${row.original.id}`} className="font-medium hover:underline">
            {row.original.po_number}
          </Link>
        ),
      },
      {
        accessorKey: "supplier_id",
        header: ({ column }) => <SortableHeader column={column} title="Supplier" />,
      },
      {
        accessorKey: "warehouse_id",
        header: ({ column }) => <SortableHeader column={column} title="Warehouse" />,
      },
      {
        accessorKey: "order_date",
        header: ({ column }) => <SortableHeader column={column} title="Order Date" />,
        cell: ({ row }) => formatDate(row.original.order_date),
      },
      {
        accessorKey: "expected_delivery_date",
        header: ({ column }) => <SortableHeader column={column} title="Expected Delivery" />,
        cell: ({ row }) => formatDate(row.original.expected_delivery_date),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <Badge variant="outline">{STATUS_LABEL[row.original.status]}</Badge>,
      },
      {
        id: "risk",
        header: "Risk",
        cell: ({ row }) =>
          row.original.is_at_risk ? <Badge variant="destructive">At risk</Badge> : null,
      },
    ],
    []
  );

  return (
    <DataTable columns={columns} data={purchaseOrders} searchKey="po_number" searchPlaceholder="Search PO number…" />
  );
}
