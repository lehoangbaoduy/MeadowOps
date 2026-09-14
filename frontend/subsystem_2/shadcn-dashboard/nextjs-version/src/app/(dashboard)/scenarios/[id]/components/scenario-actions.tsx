"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

import type { ScenarioStatus } from "../../types";

/**
 * app.domain.scenario.validate_for_approval raises errors keyed by the
 * dotted backend field name (e.g. "ground_truth.supporting_signals must be
 * a non-empty list"). Those don't match this page's own labels (Edit
 * narrative's "Supporting signals (one per line)", Ground Truth Preview's
 * "Supporting signals") — a Builder searching the page for an input
 * literally named "ground_truth.supporting_signals" won't find one, even
 * though the matching field is right there under a different label. Found
 * live: a Builder hit exactly this after clicking Approve on a freshly
 * created scenario without running Regenerate or filling in Edit narrative
 * first. Translate the backend's field names to this page's own labels
 * before showing the error.
 */
const GROUND_TRUTH_FIELD_LABELS: Record<string, string> = {
  known_cause: "Known cause",
  evidence: "Evidence",
  supporting_signals: "Supporting signals",
  distractors: "Distractors",
  expected_considerations: "Expected considerations",
  acceptable_conclusions: "Acceptable conclusions",
  unacceptable_conclusions: "Unacceptable conclusions",
  uncertainty: "Uncertainty",
};

function humanizeValidationError(error: string): string {
  return error.replace(/ground_truth\.(\w+)/, (match, field: string) => {
    return GROUND_TRUTH_FIELD_LABELS[field] ?? match;
  });
}

/**
 * The approve route (backend/app/api/admin_scenarios.py) can return
 * `detail` as either a plain string (404/409) or `{errors: [...]}` (422,
 * ScenarioValidationError) — code review of this unit (MEDIUM) flagged
 * assuming a uniform string shape as a guaranteed "Objects are not valid
 * as a React child" crash on the one response a Builder most needs to
 * read.
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
      return (detail as { errors: string[] })
        .errors.map(humanizeValidationError)
        .join("; ");
    }
  }
  return "Request failed";
}

type Action = "regenerate" | "approve" | "activate" | "cancel";

const ACTION_LABEL: Record<Action, string> = {
  regenerate: "Regenerate",
  approve: "Approve",
  activate: "Activate",
  cancel: "Cancel",
};

const ACTION_CONFIRM: Record<Action, string | null> = {
  regenerate: "Re-derive known cause and evidence from the source exception flag? Your narrative edits (known cause, distractors, etc.) are kept.",
  approve: null,
  activate: null,
  cancel: "Cancel this scenario? This cannot be undone.",
};

function availableActions(status: ScenarioStatus): Action[] {
  if (status === "draft") return ["regenerate", "approve", "cancel"];
  if (status === "approved") return ["activate", "cancel"];
  return [];
}

export function ScenarioActions({ id, status }: { id: string; status: ScenarioStatus }) {
  const router = useRouter();
  const [pending, setPending] = useState<Action | null>(null);
  const actions = availableActions(status);

  if (actions.length === 0) return null;

  async function run(action: Action) {
    const confirmMessage = ACTION_CONFIRM[action];
    if (confirmMessage && !window.confirm(confirmMessage)) return;

    setPending(action);
    try {
      const response = await fetch(`/api/scenarios/${id}/${action}`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(extractErrorMessage(body));
        return;
      }
      toast.success(`Scenario ${action === "cancel" ? "cancelled" : `${action}d`}`);
      router.refresh();
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((action) => (
        <Button
          key={action}
          variant={action === "cancel" ? "destructive" : action === "approve" || action === "activate" ? "default" : "outline"}
          disabled={pending !== null}
          onClick={() => run(action)}
        >
          {pending === action ? `${ACTION_LABEL[action]}…` : ACTION_LABEL[action]}
        </Button>
      ))}
    </div>
  );
}
