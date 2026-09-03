"use client";

import * as React from "react";
import { type ColumnDef } from "@tanstack/react-table";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";

/**
 * Unit 12c (MEADOWOPS-API-006): read-only Customer list (PRD Appendix D.1 —
 * "Direct entity match", no CRUD requirement per S1-FR-12). Deliberately no
 * create/edit dialog or actions column, unlike master-data-crud.tsx's four
 * CRUD entities — this table only ever renders what the server already
 * fetched (see app/(app)/customers/page.tsx).
 */
export type CustomerRow = {
  id: string;
  name: string;
  service_priority: "standard" | "priority" | "critical";
  warehouse_id: string;
  region: string;
  is_active: boolean;
};

const SERVICE_PRIORITY_LABEL: Record<CustomerRow["service_priority"], string> = {
  standard: "Standard",
  priority: "Priority",
  critical: "Critical",
};

export function CustomersTable({ customers }: { customers: CustomerRow[] }) {
  const columns = React.useMemo<ColumnDef<CustomerRow>[]>(
    () => [
      {
        accessorKey: "id",
        header: ({ column }) => <SortableHeader column={column} title="ID" />,
      },
      {
        accessorKey: "name",
        header: ({ column }) => <SortableHeader column={column} title="Name" />,
      },
      {
        accessorKey: "service_priority",
        header: ({ column }) => <SortableHeader column={column} title="Service Priority" />,
        cell: ({ row }) => SERVICE_PRIORITY_LABEL[row.original.service_priority],
      },
      {
        accessorKey: "warehouse_id",
        header: ({ column }) => <SortableHeader column={column} title="Warehouse" />,
      },
      {
        accessorKey: "region",
        header: ({ column }) => <SortableHeader column={column} title="Region" />,
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) => (
          <Badge variant={row.original.is_active ? "default" : "secondary"}>
            {row.original.is_active ? "Active" : "Inactive"}
          </Badge>
        ),
      },
    ],
    []
  );

  return (
    <DataTable columns={columns} data={customers} searchKey="name" searchPlaceholder="Search customers…" />
  );
}
