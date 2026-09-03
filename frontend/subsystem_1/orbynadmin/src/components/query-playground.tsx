"use client";

import * as React from "react";
import CodeMirror from "@uiw/react-codemirror";
import { sql } from "@codemirror/lang-sql";
import { IconAlertTriangle, IconPlayerPlay, IconRefresh } from "@tabler/icons-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface StatementPreview {
  sql: string;
  statement_type: string;
}

interface ExecuteResult {
  status: "success" | "error" | "timed_out" | "confirmation_required";
  columns?: string[];
  rows?: Record<string, unknown>[];
  row_count?: number;
  truncated?: boolean;
  duration_ms?: number;
  error_message?: string | null;
  statements?: StatementPreview[];
}

interface QueryLogEntry {
  id: string;
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

export function QueryPlayground() {
  const [statement, setStatement] = React.useState("select * from product limit 50;");
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<ExecuteResult | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = React.useState<StatementPreview[] | null>(
    null
  );
  const [history, setHistory] = React.useState<QueryLogEntry[]>([]);
  const [refreshing, setRefreshing] = React.useState(false);

  const loadHistory = React.useCallback(async () => {
    try {
      const response = await fetch("/api/query/history", { cache: "no-store" });
      if (response.ok) {
        setHistory(await response.json());
      } else {
        toast.error("Failed to load query history");
      }
    } catch {
      toast.error("Failed to load query history");
    }
  }, []);

  React.useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  async function runQuery(confirmed: boolean) {
    setRunning(true);
    try {
      const response = await fetch("/api/query/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql: statement, confirmed }),
      });
      const body: ExecuteResult = await response.json();
      if (!response.ok) {
        toast.error(typeof body === "object" && "detail" in body ? String(body.detail) : "Query failed");
        return;
      }
      if (body.status === "confirmation_required") {
        setPendingConfirmation(body.statements ?? []);
        return;
      }
      setResult(body);
      void loadHistory();
    } catch {
      toast.error("Query failed — check your connection and try again");
    } finally {
      setRunning(false);
    }
  }

  async function confirmAndRun() {
    setPendingConfirmation(null);
    await runQuery(true);
  }

  async function declineConfirmation() {
    setPendingConfirmation(null);
    try {
      const response = await fetch("/api/query/cancel-confirmation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql: statement }),
      });
      if (!response.ok) {
        toast.error("Failed to record the cancelled query");
        return;
      }
      void loadHistory();
    } catch {
      toast.error("Failed to record the cancelled query");
    }
  }

  async function doRefreshSandbox() {
    setRefreshing(true);
    try {
      const response = await fetch("/api/query/refresh-sandbox", { method: "POST" });
      const body = await response.json();
      if (!response.ok) {
        toast.error(typeof body?.detail === "string" ? body.detail : "Refresh failed");
        return;
      }
      if (body.status !== "complete") {
        toast.error(body.error ?? "Sandbox refresh failed");
        return;
      }
      toast.success(`Sandbox refreshed — ${body.tables_mirrored} tables mirrored`);
    } catch {
      toast.error("Sandbox refresh failed — check your connection and try again");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border">
        <CodeMirror
          value={statement}
          height="220px"
          extensions={[sql()]}
          onChange={(value) => setStatement(value)}
        />
      </div>

      <div className="flex items-center gap-2">
        <Button onClick={() => void runQuery(false)} disabled={running || statement.trim() === ""}>
          <IconPlayerPlay className="size-4" />
          {running ? "Running…" : "Run"}
        </Button>
        <Button variant="outline" onClick={() => void doRefreshSandbox()} disabled={refreshing}>
          <IconRefresh className="size-4" />
          {refreshing ? "Refreshing…" : "Refresh sandbox"}
        </Button>
      </div>

      {result && (
        <div className="space-y-3">
          {result.status === "error" && (
            <Alert variant="destructive">
              <IconAlertTriangle className="size-4" />
              <AlertTitle>Query failed</AlertTitle>
              <AlertDescription className="font-mono text-xs whitespace-pre-wrap">
                {result.error_message}
              </AlertDescription>
            </Alert>
          )}
          {result.status === "timed_out" && (
            <Alert variant="destructive">
              <IconAlertTriangle className="size-4" />
              <AlertTitle>Query timed out</AlertTitle>
              <AlertDescription>{result.error_message}</AlertDescription>
            </Alert>
          )}
          {result.status === "success" && (
            <>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>{result.row_count} row(s)</span>
                <span>·</span>
                <span>{result.duration_ms}ms</span>
                {result.truncated && (
                  <Badge variant="secondary">Truncated to {result.row_count} rows</Badge>
                )}
              </div>
              {(result.columns?.length ?? 0) > 0 && (
                <div className="overflow-x-auto rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {result.columns!.map((col) => (
                          <TableHead key={col}>{col}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.rows!.map((row, i) => (
                        <TableRow key={i}>
                          {result.columns!.map((col) => (
                            <TableCell key={col} className="font-mono text-xs">
                              {row[col] === null ? (
                                <span className="text-muted-foreground italic">NULL</span>
                              ) : (
                                String(row[col])
                              )}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <Tabs defaultValue="history">
        <TabsList>
          <TabsTrigger value="history">Query history</TabsTrigger>
        </TabsList>
        <TabsContent value="history">
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Submitted</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Rows</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Query</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground">
                      No queries submitted yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  history.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {new Date(entry.submitted_at).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <Badge variant={STATEMENT_TYPE_VARIANT[entry.statement_type] ?? "secondary"}>
                          {entry.statement_type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={RESULT_STATUS_VARIANT[entry.result_status] ?? "secondary"}>
                          {entry.result_status}
                        </Badge>
                      </TableCell>
                      <TableCell>{entry.row_count ?? "—"}</TableCell>
                      <TableCell>{entry.duration_ms != null ? `${entry.duration_ms}ms` : "—"}</TableCell>
                      <TableCell className="max-w-xs truncate font-mono text-xs">
                        {entry.query_text}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={pendingConfirmation !== null} onOpenChange={(open) => !open && setPendingConfirmation(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <IconAlertTriangle className="size-5 text-destructive" />
              Confirm before running
            </DialogTitle>
            <DialogDescription>
              This submission includes a statement that changes data or schema. Review it below
              before running — this cannot be undone once confirmed.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {pendingConfirmation?.map((stmt, i) => (
              <div key={i} className="rounded-md border p-2">
                <Badge variant={STATEMENT_TYPE_VARIANT[stmt.statement_type] ?? "secondary"} className="mb-1">
                  {stmt.statement_type}
                </Badge>
                <pre className="overflow-x-auto font-mono text-xs whitespace-pre-wrap">{stmt.sql}</pre>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => void declineConfirmation()}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => void confirmAndRun()}>
              Run anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
