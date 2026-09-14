"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import { DIFFICULTY_RECOMMENDATION_LABEL, type Evaluation, type ThreadStatus } from "../thread-types";
import { HumanReviewSection } from "./human-review-section";
import { PortfolioExportDialog } from "./portfolio-export-dialog";

function extractErrorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

type LoadState = "loading" | "none" | "loaded" | "error";

const EVALUATION_FIELDS: { key: keyof Evaluation; label: string }[] = [
  { key: "strengths", label: "Strengths" },
  { key: "gaps", label: "Gaps" },
  { key: "evidence", label: "Evidence" },
  { key: "senior_analyst_pushback", label: "Senior analyst pushback" },
  { key: "final_verdict", label: "Final verdict" },
  { key: "suggested_next_skill_focus", label: "Suggested next skill focus" },
];

export function EvaluationPanel({
  threadId,
  threadStatus,
}: {
  threadId: string;
  threadStatus: ThreadStatus;
}) {
  const [state, setState] = useState<LoadState>("loading");
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [completing, setCompleting] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    try {
      const response = await fetch(`/api/evaluations/threads/${threadId}`, { cache: "no-store" });
      if (response.status === 404) {
        setState("none");
        return;
      }
      if (!response.ok) {
        setState("error");
        return;
      }
      setEvaluation(await response.json());
      setState("loaded");
    } catch {
      setState("error");
    }
  }, [threadId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleComplete() {
    setCompleting(true);
    try {
      const response = await fetch(`/api/chat/threads/${threadId}/complete`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (response.status === 503) {
        toast.error("AI evaluation is not configured (no Claude client).");
        return;
      }
      if (!response.ok) {
        toast.error(extractErrorMessage(body, "Could not complete this thread"));
        return;
      }
      setEvaluation(body);
      setState("loaded");
      toast.success("Evaluation generated");
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setCompleting(false);
    }
  }

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Loading evaluation…</p>;
  }

  if (state === "error") {
    return <p className="text-sm text-destructive">Could not load this thread&rsquo;s evaluation.</p>;
  }

  if (state === "none") {
    if (threadStatus !== "open") {
      return <p className="text-sm text-muted-foreground">No evaluation for this thread yet.</p>;
    }
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          Not evaluated yet — generate a draft AI evaluation from this thread&rsquo;s ground truth.
        </p>
        <Button size="sm" onClick={handleComplete} disabled={completing} className="w-fit">
          {completing ? "Completing…" : "Complete Thread & Evaluate"}
        </Button>
      </div>
    );
  }

  if (!evaluation) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Difficulty recommendation</span>
        <Badge>{DIFFICULTY_RECOMMENDATION_LABEL[evaluation.difficulty_recommendation]}</Badge>
        <span className="text-xs text-muted-foreground">{evaluation.prompt_version}</span>
      </div>
      {EVALUATION_FIELDS.map((f) => (
        <div key={f.key}>
          <h4 className="text-sm font-semibold">{f.label}</h4>
          <p className="whitespace-pre-wrap text-sm text-muted-foreground">
            {String(evaluation[f.key])}
          </p>
        </div>
      ))}
      <HumanReviewSection threadId={threadId} />
      <PortfolioExportDialog threadId={threadId} />
    </div>
  );
}
