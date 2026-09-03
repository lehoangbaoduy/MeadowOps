"use client";

import * as React from "react";
import Link from "next/link";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/dashboard-format";
import type { Shipment } from "@/types/dashboard";

/** Unit 16: Appendix D's Shipping page ("Shipment tracking / OTIF drill-down"). */
export function ShipmentsTable({ shipments }: { shipments: Shipment[] }) {
  const columns = React.useMemo<ColumnDef<Shipment>[]>(
    () => [
      {
        accessorKey: "carrier_id",
        header: ({ column }) => <SortableHeader column={column} title="Carrier" />,
      },
      {
        accessorKey: "warehouse_id",
        header: ({ column }) => <SortableHeader column={column} title="Warehouse" />,
      },
      {
        accessorKey: "ship_date",
        header: ({ column }) => <SortableHeader column={column} title="Ship Date" />,
        cell: ({ row }) => formatDate(row.original.ship_date),
      },
      {
        accessorKey: "promised_delivery_date",
        header: ({ column }) => <SortableHeader column={column} title="Promised" />,
        cell: ({ row }) => formatDate(row.original.promised_delivery_date),
      },
      {
        accessorKey: "actual_delivery_date",
        header: ({ column }) => <SortableHeader column={column} title="Actual" />,
        cell: ({ row }) =>
          row.original.actual_delivery_date ? formatDate(row.original.actual_delivery_date) : "—",
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <Badge variant="outline">{row.original.status.replace("_", " ")}</Badge>
            {row.original.is_late && <Badge variant="destructive">Late</Badge>}
          </div>
        ),
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <Link href={`/orders/sales/${row.original.sales_order_id}`} className="text-sm hover:underline">
            View order
          </Link>
        ),
      },
    ],
    []
  );

  return <DataTable columns={columns} data={shipments} />;
}
