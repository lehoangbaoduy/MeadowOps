"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import { DIFFICULTY_RECOMMENDATION_LABEL, type PortfolioExport } from "../thread-types";

type LoadState = "idle" | "loading" | "loaded" | "not-ready" | "error";

/**
 * Unit 34 (PRD 6.10): the compiled export - embeds the full draft
 * evaluation (difficulty_recommendation included), so this stays on the
 * require_admin route/Builder-only app, never the Analyst-voiced
 * reflection form (that one lives on orbynadmin's Chat page instead - see
 * app/(app)/chat/components/reflection-form.tsx there). 409 means the
 * thread isn't completed yet (app.services.portfolio.ThreadNotCompleted
 * Error) - a normal, not-yet-ready state, not an error.
 */
export function PortfolioExportDialog({ threadId }: { threadId: string }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<LoadState>("idle");
  const [data, setData] = useState<PortfolioExport | null>(null);

  async function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next || state !== "idle") return;
    setState("loading");
    try {
      const response = await fetch(`/api/portfolio/threads/${threadId}`, { cache: "no-store" });
      if (response.status === 409) {
        setState("not-ready");
        return;
      }
      if (!response.ok) {
        setState("error");
        return;
      }
      setData(await response.json());
      setState("loaded");
    } catch {
      setState("error");
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          View Portfolio Export
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Portfolio export</DialogTitle>
        </DialogHeader>
        {state === "loading" && <p className="text-sm text-muted-foreground">Loading…</p>}
        {state === "not-ready" && (
          <p className="text-sm text-muted-foreground">
            This thread isn&rsquo;t completed yet — the export becomes available once it is.
          </p>
        )}
        {state === "error" && (
          <p className="text-sm text-destructive">Could not load the portfolio export.</p>
        )}
        {state === "loaded" && data && (
          <div className="space-y-4 text-sm">
            <div>
              <h4 className="font-semibold">{data.scenario.title}</h4>
              <p className="text-muted-foreground">
                {data.scenario.scenario_type} · {data.scenario.competency_cluster}
              </p>
              {data.trigger && <p className="mt-1 whitespace-pre-wrap">{data.trigger}</p>}
            </div>

            <div>
              <h4 className="font-semibold">Transcript</h4>
              <div className="mt-2 space-y-2">
                {data.messages.map((m, i) => (
                  <div key={i} className="rounded-md border p-2">
                    <p className="text-xs font-medium text-muted-foreground">
                      {m.sender_role === "analyst" ? "Analyst" : "Builder"}
                    </p>
                    <p className="whitespace-pre-wrap">{m.body}</p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h4 className="font-semibold">Evaluation</h4>
                <Badge>
                  {DIFFICULTY_RECOMMENDATION_LABEL[data.evaluation.difficulty_recommendation]}
                </Badge>
              </div>
              <p className="mt-1 whitespace-pre-wrap">{data.evaluation.final_verdict}</p>
            </div>

            {data.human_review ? (
              <div>
                <h4 className="font-semibold">Human review</h4>
                <p className="text-muted-foreground">
                  {data.human_review.reviewer_name} —{" "}
                  {data.human_review.verdict === "agree" ? "Agreed" : "Overrode"}
                </p>
                <p className="mt-1 whitespace-pre-wrap">{data.human_review.tier_assessment_notes}</p>
              </div>
            ) : (
              <p className="text-muted-foreground">
                No human review yet (not required for Build & Test — PRD 1.6).
              </p>
            )}

            {data.reflection ? (
              <div>
                <h4 className="font-semibold">Analyst reflection</h4>
                <p className="mt-1 whitespace-pre-wrap">{data.reflection.reflection_what_happened}</p>
              </div>
            ) : (
              <p className="text-muted-foreground">
                No reflection submitted yet (not required for Build & Test — PRD 1.6).
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
