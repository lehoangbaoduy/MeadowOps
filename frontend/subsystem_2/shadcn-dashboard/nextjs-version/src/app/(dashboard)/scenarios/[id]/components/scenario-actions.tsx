"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

import type { ScenarioStatus } from "../../types";

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
      return (detail as { errors: string[] }).errors.join("; ");
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
