"use client";

import * as React from "react";
import Link from "next/link";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { InventoryPosition } from "@/types/dashboard";

/** Unit 16 (MEADOWOPS-API-003): Inventory Position view (S1-FR-5). */
export function InventoryTable({ positions }: { positions: InventoryPosition[] }) {
  const columns = React.useMemo<ColumnDef<InventoryPosition>[]>(
    () => [
      {
        accessorKey: "product_id",
        header: ({ column }) => <SortableHeader column={column} title="Product" />,
      },
      {
        accessorKey: "warehouse_id",
        header: ({ column }) => <SortableHeader column={column} title="Warehouse" />,
      },
      {
        accessorKey: "quantity_on_hand",
        header: ({ column }) => <SortableHeader column={column} title="On Hand" />,
        cell: ({ row }) => row.original.quantity_on_hand ?? "—",
      },
      {
        accessorKey: "quantity_allocated",
        header: ({ column }) => <SortableHeader column={column} title="Allocated" />,
        cell: ({ row }) => row.original.quantity_allocated ?? "—",
      },
      {
        accessorKey: "days_of_supply",
        header: ({ column }) => <SortableHeader column={column} title="Days of Supply" />,
        cell: ({ row }) => row.original.days_of_supply ?? "—",
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) =>
          row.original.is_low_stock ? (
            <Badge variant="destructive">Low stock</Badge>
          ) : (
            <Badge variant="secondary">OK</Badge>
          ),
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <Button variant="ghost" size="sm" asChild>
            <Link
              href={`/inventory/${encodeURIComponent(row.original.product_id)}/${encodeURIComponent(row.original.warehouse_id)}`}
            >
              Transactions
            </Link>
          </Button>
        ),
      },
    ],
    []
  );

  return (
    <DataTable columns={columns} data={positions} searchKey="product_id" searchPlaceholder="Search products…" />
  );
}
