"use client";

import * as React from "react";
import Link from "next/link";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/dashboard-format";
import type { SalesOrderSummary } from "@/types/dashboard";

const STATUS_LABEL: Record<SalesOrderSummary["status"], string> = {
  draft: "Draft",
  submitted: "Submitted",
  allocated: "Allocated",
  partially_shipped: "Partially shipped",
  shipped: "Shipped",
  cancelled: "Cancelled",
};

export function SalesOrdersTable({ salesOrders }: { salesOrders: SalesOrderSummary[] }) {
  const columns = React.useMemo<ColumnDef<SalesOrderSummary>[]>(
    () => [
      {
        accessorKey: "so_number",
        header: ({ column }) => <SortableHeader column={column} title="SO Number" />,
        cell: ({ row }) => (
          <Link href={`/orders/sales/${row.original.id}`} className="font-medium hover:underline">
            {row.original.so_number}
          </Link>
        ),
      },
      {
        accessorKey: "customer_id",
        header: ({ column }) => <SortableHeader column={column} title="Customer" />,
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
        accessorKey: "promised_date",
        header: ({ column }) => <SortableHeader column={column} title="Promised" />,
        cell: ({ row }) => (row.original.promised_date ? formatDate(row.original.promised_date) : "—"),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <Badge variant="outline">{STATUS_LABEL[row.original.status]}</Badge>,
      },
    ],
    []
  );

  return (
    <DataTable columns={columns} data={salesOrders} searchKey="so_number" searchPlaceholder="Search SO number…" />
  );
}
