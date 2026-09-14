"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  DIFFICULTY_RECOMMENDATION_LABEL,
  type DifficultyRecommendation,
  type HumanReview,
  type HumanReviewVerdict,
} from "../thread-types";

const DIFFICULTY_OPTIONS: DifficultyRecommendation[] = ["foundational", "standard", "stretch", "hold"];

function extractErrorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

type LoadState = "loading" | "none" | "loaded";

/**
 * Unit 34 (PRD 6.6 step 11, ER-3/ER-4): the External Human Reviewer has no
 * account of their own in this phase (PRD 14's Open Items) - the Builder
 * stands in and submits this form directly, same as the QA test-analyst
 * harness already has her play the Analyst's role elsewhere.
 */
export function HumanReviewSection({ threadId }: { threadId: string }) {
  const [state, setState] = useState<LoadState>("loading");
  const [review, setReview] = useState<HumanReview | null>(null);
  const [reviewerName, setReviewerName] = useState("");
  const [verdict, setVerdict] = useState<HumanReviewVerdict | "">("");
  const [notes, setNotes] = useState("");
  const [overridden, setOverridden] = useState<DifficultyRecommendation | "">("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    const response = await fetch(`/api/evaluations/threads/${threadId}/human-review`, {
      cache: "no-store",
    });
    if (response.status === 404) {
      setState("none");
      return;
    }
    if (response.ok) {
      setReview(await response.json());
      setState("loaded");
      return;
    }
    setState("none");
  }, [threadId]);

  useEffect(() => {
    void load();
  }, [load]);

  const canSubmit =
    reviewerName.trim().length > 0 &&
    Boolean(verdict) &&
    notes.trim().length > 0 &&
    (verdict !== "override" || Boolean(overridden));

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const response = await fetch(`/api/evaluations/threads/${threadId}/human-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewer_name: reviewerName.trim(),
          verdict,
          tier_assessment_notes: notes.trim(),
          overridden_recommendation: verdict === "override" ? overridden : null,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(extractErrorMessage(body, "Could not record the human review"));
        return;
      }
      setReview(body);
      setState("loaded");
      toast.success("Human review recorded");
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setSubmitting(false);
    }
  }

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Loading human review…</p>;
  }

  if (state === "loaded" && review) {
    return (
      <div className="rounded-lg border p-3">
        <h4 className="text-sm font-semibold">Human review</h4>
        <p className="text-sm text-muted-foreground">
          {review.reviewer_name} — {review.verdict === "agree" ? "Agreed" : "Overrode"}
          {review.overridden_recommendation
            ? ` (${DIFFICULTY_RECOMMENDATION_LABEL[review.overridden_recommendation]})`
            : ""}
        </p>
        <p className="mt-1 whitespace-pre-wrap text-sm">{review.tier_assessment_notes}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <h4 className="text-sm font-semibold">Record human review</h4>
      <div className="grid gap-2">
        <Label htmlFor="reviewer_name">Reviewer name</Label>
        <Input
          id="reviewer_name"
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
        />
      </div>
      <div className="grid gap-2">
        <Label>Verdict</Label>
        <Select value={verdict} onValueChange={(v) => setVerdict(v as HumanReviewVerdict)}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select a verdict" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="agree">Agree with AI recommendation</SelectItem>
            <SelectItem value="override">Override AI recommendation</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {verdict === "override" && (
        <div className="grid gap-2">
          <Label>Overridden recommendation</Label>
          <Select
            value={overridden}
            onValueChange={(v) => setOverridden(v as DifficultyRecommendation)}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select a recommendation" />
            </SelectTrigger>
            <SelectContent>
              {DIFFICULTY_OPTIONS.map((d) => (
                <SelectItem key={d} value={d}>
                  {DIFFICULTY_RECOMMENDATION_LABEL[d]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div className="grid gap-2">
        <Label htmlFor="tier_notes">Tier assessment notes</Label>
        <Textarea id="tier_notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      <Button size="sm" onClick={handleSubmit} disabled={submitting || !canSubmit}>
        {submitting ? "Saving…" : "Save human review"}
      </Button>
    </div>
  );
}
