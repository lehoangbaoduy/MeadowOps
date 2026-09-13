"use client";

import * as React from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { IconMaximize } from "@tabler/icons-react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DataTable, SortableHeader } from "@/components/data-table";

export interface AdminQueryLogEntry {
  id: string;
  user_email: string;
  query_text: string;
  statement_type: string;
  result_status: string;
  row_count: number | null;
  duration_ms: number | null;
  error_message: string | null;
  submitted_at: string;
}

const STATEMENT_TYPE_VARIANT: Record<string, "default" | "destructive" | "secondary"> = {
  read: "secondary",
  write: "destructive",
  unknown: "destructive",
};

const RESULT_STATUS_VARIANT: Record<string, "default" | "destructive" | "secondary"> = {
  success: "default",
  error: "destructive",
  timed_out: "destructive",
  cancelled: "secondary",
};

export function AdminQueryLogTable({ initialData }: { initialData: AdminQueryLogEntry[] }) {
  const [expanded, setExpanded] = React.useState<AdminQueryLogEntry | null>(null);

  const columns = React.useMemo<ColumnDef<AdminQueryLogEntry>[]>(
    () => [
      {
        accessorKey: "submitted_at",
        header: ({ column }) => <SortableHeader column={column} title="Submitted" />,
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            {new Date(row.original.submitted_at).toLocaleString()}
          </span>
        ),
      },
      {
        accessorKey: "user_email",
        header: ({ column }) => <SortableHeader column={column} title="User" />,
      },
      {
        accessorKey: "statement_type",
        header: "Type",
        cell: ({ row }) => (
          <Badge variant={STATEMENT_TYPE_VARIANT[row.original.statement_type] ?? "secondary"}>
            {row.original.statement_type}
          </Badge>
        ),
      },
      {
        accessorKey: "result_status",
        header: "Status",
        cell: ({ row }) => (
          <Badge variant={RESULT_STATUS_VARIANT[row.original.result_status] ?? "secondary"}>
            {row.original.result_status}
          </Badge>
        ),
      },
      {
        accessorKey: "row_count",
        header: "Rows",
        cell: ({ row }) => row.original.row_count ?? "—",
      },
      {
        accessorKey: "duration_ms",
        header: "Duration",
        cell: ({ row }) =>
          row.original.duration_ms != null ? `${row.original.duration_ms}ms` : "—",
      },
      {
        id: "query_text",
        header: "Query",
        cell: ({ row }) => (
          <button
            type="button"
            onClick={() => setExpanded(row.original)}
            className="flex max-w-xs items-center gap-1 truncate font-mono text-xs text-left hover:underline"
          >
            <IconMaximize className="size-3 shrink-0 text-muted-foreground" />
            <span className="truncate">{row.original.query_text}</span>
          </button>
        ),
      },
    ],
    []
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={initialData}
        searchKey="user_email"
        searchPlaceholder="Search by user email…"
      />

      <Dialog open={expanded !== null} onOpenChange={(open) => !open && setExpanded(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Submitted query</DialogTitle>
            <DialogDescription>
              {expanded && (
                <>
                  {expanded.user_email} · {new Date(expanded.submitted_at).toLocaleString()}
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs whitespace-pre-wrap">
            {expanded?.query_text}
          </pre>
          {expanded?.error_message && (
            <pre className="overflow-auto rounded-md border border-destructive/50 bg-destructive/10 p-3 font-mono text-xs whitespace-pre-wrap text-destructive">
              {expanded.error_message}
            </pre>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
