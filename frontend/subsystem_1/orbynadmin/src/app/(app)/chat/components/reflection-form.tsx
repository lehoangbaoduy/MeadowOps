"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const MAX_REFLECTION_ANSWER_LENGTH = 4000;

type ReflectionFields = {
  reflection_what_happened: string;
  reflection_initial_thought: string;
  reflection_evidence_that_mattered: string;
  reflection_what_missed: string;
  reflection_what_changed_after_pushback: string;
  reflection_what_differently: string;
  reflection_skill_improved: string;
};

const QUESTIONS: { field: keyof ReflectionFields; label: string }[] = [
  { field: "reflection_what_happened", label: "What happened in this scenario?" },
  { field: "reflection_initial_thought", label: "What did you initially think was going on?" },
  { field: "reflection_evidence_that_mattered", label: "What evidence mattered most?" },
  { field: "reflection_what_missed", label: "What did you miss, if anything?" },
  {
    field: "reflection_what_changed_after_pushback",
    label: "What changed in your thinking after pushback?",
  },
  { field: "reflection_what_differently", label: "What would you do differently next time?" },
  { field: "reflection_skill_improved", label: "What skill did this improve?" },
];

const EMPTY_FIELDS: ReflectionFields = {
  reflection_what_happened: "",
  reflection_initial_thought: "",
  reflection_evidence_that_mattered: "",
  reflection_what_missed: "",
  reflection_what_changed_after_pushback: "",
  reflection_what_differently: "",
  reflection_skill_improved: "",
};

function extractErrorMessage(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "Could not submit your reflection.";
}

/**
 * Unit 34 (PRD 6.10, app.api.portfolio.record_reflection_route): shown by
 * ThreadView in place of the composer once a thread is completed
 * (app.schemas.chat.ThreadStatus, set by Subsystem 2's Builder-driven
 * /complete action). Submitted at most once - the backend's own unique
 * constraint on (thread_id) is the real enforcement (record_reflection_
 * route's IntegrityError handler); a 409 here just means a reflection was
 * already recorded (possibly from another session), so it's treated as
 * "already submitted," not an error.
 */
export function ReflectionForm({ threadId }: { threadId: string }) {
  const [fields, setFields] = useState<ReflectionFields>(EMPTY_FIELDS);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = QUESTIONS.every((q) => fields[q.field].trim().length > 0);

  function setField(field: keyof ReflectionFields, value: string) {
    setFields((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/chat/threads/${threadId}/reflection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (response.status === 409) {
        setSubmitted(true);
        return;
      }
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        setError(extractErrorMessage(body));
        return;
      }
      setSubmitted(true);
    } catch {
      setError("Could not reach the server");
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        This scenario is complete. Your reflection has been recorded — thank you.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <h3 className="text-sm font-semibold">This scenario is complete</h3>
        <p className="text-sm text-muted-foreground">
          Take a moment to reflect on how it went before moving on.
        </p>
      </div>
      {QUESTIONS.map((q) => (
        <div key={q.field} className="grid gap-2">
          <Label htmlFor={q.field}>{q.label}</Label>
          <Textarea
            id={q.field}
            rows={2}
            maxLength={MAX_REFLECTION_ANSWER_LENGTH}
            value={fields[q.field]}
            onChange={(e) => setField(q.field, e.target.value)}
          />
        </div>
      ))}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button onClick={handleSubmit} disabled={submitting || !canSubmit}>
        {submitting ? "Submitting…" : "Submit reflection"}
      </Button>
    </div>
  );
}
