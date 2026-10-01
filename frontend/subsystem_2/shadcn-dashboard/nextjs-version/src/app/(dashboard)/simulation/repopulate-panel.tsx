"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";

// Must match app.schemas.admin_simulation.CONFIRM_PHRASE - the backend
// rejects anything else, this just lets the button stay disabled until typed.
const CONFIRM_PHRASE = "REPOPULATE";
const POLL_INTERVAL_MS = 2000;

interface RepopulateStatus {
  state: "idle" | "running" | "succeeded" | "failed";
  started_at: string | null;
  finished_at: string | null;
  days_done: number;
  days_total: number;
  message: string | null;
}

function errorDetail(body: { detail?: unknown }): string {
  if (typeof body.detail === "string") return body.detail;
  return "Could not start the rebuild";
}

/**
 * Unit 40: "Reset & regenerate to today". Destructive, so it needs the typed
 * word before it enables (the backend enforces the same word). The rebuild
 * runs for a while on the server; this polls its status and reports the
 * outcome, including after a page reload mid-run.
 */
export function RepopulatePanel() {
  const router = useRouter();
  const [typed, setTyped] = useState("");
  const [status, setStatus] = useState<RepopulateStatus | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const wasRunning = useRef(false);

  const refreshStatus = useCallback(async () => {
    try {
      const response = await fetch("/api/simulation/repopulate/status", { cache: "no-store" });
      if (response.ok) setStatus((await response.json()) as RepopulateStatus);
    } catch {
      // A missed poll is harmless; the next one catches up.
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const isRunning = status?.state === "running";

  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(() => void refreshStatus(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isRunning, refreshStatus]);

  useEffect(() => {
    if (wasRunning.current && status?.state === "succeeded") {
      toast.success("Simulation rebuilt");
      router.refresh();
    }
    if (wasRunning.current && status?.state === "failed") {
      toast.error("The rebuild failed");
    }
    wasRunning.current = isRunning;
  }, [isRunning, status?.state, router]);

  async function handleStart() {
    setIsStarting(true);
    try {
      const response = await fetch("/api/simulation/repopulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: typed }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(errorDetail(body));
        return;
      }
      setTyped("");
      setStatus(body as RepopulateStatus);
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setIsStarting(false);
    }
  }

  const percent =
    status && status.days_total > 0 ? Math.round((status.days_done / status.days_total) * 100) : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Reset &amp; regenerate to today</CardTitle>
        <CardDescription>
          Rebuilds the company&apos;s recent history so it ends on today&apos;s real date, with
          fresh orders, shipments, stock levels, KPIs and exceptions.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 text-sm sm:grid-cols-2">
          <div className="space-y-1">
            <p className="font-medium">Replaced</p>
            <ul className="text-muted-foreground list-disc space-y-0.5 pl-5">
              <li>Sales and purchase orders, shipments, transfers</li>
              <li>Stock movements and inventory snapshots</li>
              <li>KPI history and exception flags</li>
              <li>
                Every draft, approved and active scenario is <strong>cancelled</strong>, because
                the exceptions it was built from are rebuilt
              </li>
            </ul>
          </div>
          <div className="space-y-1">
            <p className="font-medium">Kept</p>
            <ul className="text-muted-foreground list-disc space-y-0.5 pl-5">
              <li>Products, warehouses, suppliers, customers, carriers</li>
              <li>Users and sign-ins</li>
              <li>Scenarios (as history), chat threads, evaluations and the decision ledger</li>
            </ul>
          </div>
        </div>
        <p className="text-muted-foreground text-xs">
          The Analyst&apos;s query sandbox is refreshed at the end. After the reset the simulation
          clock keeps advancing on its schedule (one simulated day per run), so it moves past
          today&apos;s real date again; repeat the reset whenever you want it re-anchored.
        </p>

        {isRunning ? (
          <div className="space-y-2" role="status" aria-live="polite">
            <p className="text-sm font-medium">
              Rebuilding… {status.days_total > 0 ? `day ${status.days_done} of ${status.days_total}` : "starting"}
            </p>
            <Progress value={percent} />
          </div>
        ) : (
          <div className="grid max-w-sm gap-2">
            <Label htmlFor="repopulate_confirm">
              Type <span className="font-mono font-semibold">{CONFIRM_PHRASE}</span> to confirm
            </Label>
            <Input
              id="repopulate_confirm"
              autoComplete="off"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
            <Button
              variant="destructive"
              onClick={handleStart}
              disabled={typed !== CONFIRM_PHRASE || isStarting}
            >
              {isStarting ? "Starting…" : "Reset & regenerate to today"}
            </Button>
          </div>
        )}

        {status?.state === "succeeded" && status.message && (
          <p role="status" className="text-sm">
            {status.message}
          </p>
        )}
        {status?.state === "failed" && status.message && (
          <p role="alert" className="text-destructive text-sm">
            {status.message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
