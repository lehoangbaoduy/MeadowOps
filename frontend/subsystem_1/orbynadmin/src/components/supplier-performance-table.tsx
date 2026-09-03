"use client";

import * as React from "react";
import Link from "next/link";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import type { SupplierPerformance } from "@/types/dashboard";

/** Unit 16 (MEADOWOPS-API-003): Supplier view — net-new per S1-FR-5, no
 * PRD Appendix D page mapping exists for it (spec id 207). */
export function SupplierPerformanceTable({ suppliers }: { suppliers: SupplierPerformance[] }) {
  const columns = React.useMemo<ColumnDef<SupplierPerformance>[]>(
    () => [
      {
        accessorKey: "supplier_name",
        header: ({ column }) => <SortableHeader column={column} title="Supplier" />,
        cell: ({ row }) => (
          <Link href={`/suppliers/${row.original.supplier_id}`} className="font-medium hover:underline">
            {row.original.supplier_name}
          </Link>
        ),
      },
      {
        accessorKey: "total_purchase_order_count",
        header: ({ column }) => <SortableHeader column={column} title="Total POs" />,
      },
      {
        accessorKey: "open_purchase_order_count",
        header: ({ column }) => <SortableHeader column={column} title="Open POs" />,
      },
      {
        accessorKey: "at_risk_purchase_order_count",
        header: ({ column }) => <SortableHeader column={column} title="At Risk" />,
        cell: ({ row }) =>
          row.original.at_risk_purchase_order_count > 0 ? (
            <Badge variant="destructive">{row.original.at_risk_purchase_order_count}</Badge>
          ) : (
            row.original.at_risk_purchase_order_count
          ),
      },
    ],
    []
  );

  return (
    <DataTable
      columns={columns}
      data={suppliers}
      searchKey="supplier_name"
      searchPlaceholder="Search suppliers…"
    />
  );
}
