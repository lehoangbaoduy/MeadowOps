"use client";

import { useState } from "react";
import { Check, Copy, Play } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface RunResult {
  status: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  duration_ms: number;
  error_message: string | null;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * Unit 38 (MEADOWOPS-DOM-026): the suggested query that should resolve the
 * scenario, so the Builder can check the Analyst's work and nudge her if
 * she is stuck. Builder-only by construction - it lives in ground_truth,
 * which no Analyst or persona path reads. The query text is rendered as a
 * plain text node (React escapes it); "Run" goes through the admin-only
 * backend route, which re-validates it as a single SELECT and runs it as the
 * restricted sandbox role.
 */
export function ExpectedQueryPanel({ id, query }: { id: string; query: string }) {
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleRun() {
    setIsRunning(true);
    try {
      const response = await fetch(`/api/scenarios/${id}/expected-query/run`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(typeof body.detail === "string" ? body.detail : "Could not run the query");
        return;
      }
      setResult(body as RunResult);
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setIsRunning(false);
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(query);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy to the clipboard");
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">Expected query</CardTitle>
          <Badge variant="secondary">Builder only</Badge>
        </div>
        <CardDescription>
          A query that should surface the problem. Use it to check the Analyst&apos;s work or to
          nudge her if she is stuck. She never sees this.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {query ? (
          <>
            <pre
              aria-label="Expected query"
              className="bg-muted overflow-x-auto rounded-md border p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap"
            >
              {query}
            </pre>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={handleRun} disabled={isRunning}>
                <Play className="size-4" />
                {isRunning ? "Running…" : "Run against sandbox"}
              </Button>
              <Button size="sm" variant="outline" onClick={handleCopy}>
                {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
                {copied ? "Copied" : "Copy"}
              </Button>
              <p className="text-muted-foreground text-xs">
                Runs against the sandbox as it is now, so numbers can differ from when the scenario
                was created.
              </p>
            </div>
          </>
        ) : (
          <p className="text-sm italic text-muted-foreground">
            No expected query yet. Add one below, or regenerate the scenario to have it drafted.
          </p>
        )}

        {result && result.status !== "success" && (
          <p role="alert" className="text-destructive text-sm">
            {result.status === "timed_out"
              ? "The query timed out."
              : (result.error_message ?? "The query failed.")}
          </p>
        )}

        {result && result.status === "success" && (
          <div className="space-y-2">
            <p className="text-muted-foreground text-xs">
              {result.row_count} {result.row_count === 1 ? "row" : "rows"} in {result.duration_ms} ms
              {result.truncated ? " (showing the first rows only)" : ""}
            </p>
            <div className="max-h-80 overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    {result.columns.map((column) => (
                      <TableHead key={column} className="font-mono text-xs">
                        {column}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.rows.map((row, index) => (
                    <TableRow key={index}>
                      {result.columns.map((column) => (
                        <TableCell key={column} className="font-mono text-xs">
                          {formatCell(row[column])}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
