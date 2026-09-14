"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  APPROVAL_AUTHORITY_OPTIONS,
  DECISION_OUTCOME_OPTIONS,
  type ApprovalAuthority,
  type DecisionEvent,
  type DecisionEventStatus,
  type DecisionOutcome,
} from "@/types/ledger";

/**
 * Unit 34: mirrors app/(dashboard)/scenarios/[id]/components/scenario-
 * actions.tsx's extractErrorMessage exactly - app.api.ledger returns the
 * same `detail` string / `{errors: [...]}` shapes FastAPI's validation
 * errors and this project's own HTTPException handlers already produce
 * everywhere else.
 */
function extractErrorMessage(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (
      detail &&
      typeof detail === "object" &&
      "errors" in detail &&
      Array.isArray((detail as { errors: unknown }).errors)
    ) {
      return (detail as { errors: string[] }).errors.join("; ");
    }
  }
  return "Request failed";
}

type SimpleAction = "request-clarification" | "resubmit" | "reject" | "implement" | "partially-implement";

const SIMPLE_ACTION_LABEL: Record<SimpleAction, string> = {
  "request-clarification": "Request Clarification",
  resubmit: "Resubmit",
  reject: "Reject",
  implement: "Mark Implemented",
  "partially-implement": "Mark Partially Implemented",
};

const SIMPLE_ACTION_CONFIRM: Partial<Record<SimpleAction, string>> = {
  reject: "Reject this decision? This cannot be undone.",
};

function simpleActionsFor(status: DecisionEventStatus): SimpleAction[] {
  if (status === "clarification_requested") return ["resubmit"];
  if (status === "accepted") return ["implement", "partially-implement"];
  return [];
}

function runSimpleAction(action: SimpleAction, decisionId: string): Promise<Response> {
  return fetch(`/api/ledger/decisions/${decisionId}/${action}`, { method: "POST" });
}

function AcceptDialog({ decisionId }: { decisionId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [approvalAuthority, setApprovalAuthority] = useState<ApprovalAuthority | "">("");
  const [pending, setPending] = useState(false);

  async function handleAccept() {
    setPending(true);
    try {
      const response = await fetch(`/api/ledger/decisions/${decisionId}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(approvalAuthority ? { approval_authority: approvalAuthority } : {}),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(extractErrorMessage(body));
        return;
      }
      toast.success("Decision accepted");
      setOpen(false);
      router.refresh();
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">Accept</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Accept decision</DialogTitle>
        </DialogHeader>
        <div className="grid gap-2">
          <Label>Approval authority (optional)</Label>
          <Select
            value={approvalAuthority}
            onValueChange={(v) => setApprovalAuthority(v as ApprovalAuthority)}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Not specified" />
            </SelectTrigger>
            <SelectContent>
              {APPROVAL_AUTHORITY_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <DialogFooter>
          <Button onClick={handleAccept} disabled={pending}>
            {pending ? "Accepting…" : "Accept"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OutcomeDialog({ decisionId }: { decisionId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<DecisionOutcome | "">("");
  const [notes, setNotes] = useState("");
  const [pending, setPending] = useState(false);

  async function handleSubmit() {
    if (!outcome) return;
    setPending(true);
    try {
      const response = await fetch(`/api/ledger/decisions/${decisionId}/outcome`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outcome, notes: notes.trim() || null }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(extractErrorMessage(body));
        return;
      }
      toast.success("Outcome recorded");
      setOpen(false);
      router.refresh();
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">Record Outcome</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Record outcome</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>Outcome</Label>
            <Select value={outcome} onValueChange={(v) => setOutcome(v as DecisionOutcome)}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select an outcome" />
              </SelectTrigger>
              <SelectContent>
                {DECISION_OUTCOME_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="outcome_notes">Notes (optional)</Label>
            <Textarea
              id="outcome_notes"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={handleSubmit} disabled={pending || !outcome}>
            {pending ? "Saving…" : "Save outcome"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DecisionActions({ decision }: { decision: DecisionEvent }) {
  const router = useRouter();
  const [pending, setPending] = useState<SimpleAction | null>(null);

  async function run(action: SimpleAction) {
    const confirmMessage = SIMPLE_ACTION_CONFIRM[action];
    if (confirmMessage && !window.confirm(confirmMessage)) return;
    setPending(action);
    try {
      const response = await runSimpleAction(action, decision.id);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(extractErrorMessage(body));
        return;
      }
      toast.success(SIMPLE_ACTION_LABEL[action]);
      router.refresh();
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setPending(null);
    }
  }

  const simple = simpleActionsFor(decision.status);
  const showAccept = decision.status === "proposed";
  const showRequestClarification = decision.status === "proposed";
  const showReject = decision.status === "proposed";
  const showOutcome = decision.status === "implemented" || decision.status === "partially_implemented";

  if (
    !showAccept &&
    !showRequestClarification &&
    !showReject &&
    !showOutcome &&
    simple.length === 0
  ) {
    return <span className="text-muted-foreground">—</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {showRequestClarification && (
        <Button
          size="sm"
          variant="outline"
          disabled={pending !== null}
          onClick={() => run("request-clarification")}
        >
          {pending === "request-clarification" ? "…" : "Request Clarification"}
        </Button>
      )}
      {showAccept && <AcceptDialog decisionId={decision.id} />}
      {showReject && (
        <Button
          size="sm"
          variant="destructive"
          disabled={pending !== null}
          onClick={() => run("reject")}
        >
          {pending === "reject" ? "…" : "Reject"}
        </Button>
      )}
      {simple
        .filter((a) => a !== "reject")
        .map((action) => (
          <Button
            key={action}
            size="sm"
            variant="outline"
            disabled={pending !== null}
            onClick={() => run(action)}
          >
            {pending === action ? "…" : SIMPLE_ACTION_LABEL[action]}
          </Button>
        ))}
      {showOutcome && <OutcomeDialog decisionId={decision.id} />}
    </div>
  );
}
