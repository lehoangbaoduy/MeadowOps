"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import type { ScenarioGroundTruth } from "../../types";

function toLines(value: string[]): string {
  return value.join("\n");
}

function fromLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/**
 * Draft-only (backend/app/services/scenario_service.py's own
 * update_ground_truth guard) — this form is only ever rendered by the
 * parent page while `scenario.status === "draft"`. Never touches
 * `evidence`: schemas/scenario.py's GroundTruthUpdate has no field for it
 * on purpose (that block is mechanically re-derived by "regenerate", not
 * hand-edited).
 */
export function GroundTruthEditForm({
  id,
  groundTruth,
}: {
  id: string;
  groundTruth: ScenarioGroundTruth;
}) {
  const router = useRouter();
  const [knownCause, setKnownCause] = useState(groundTruth.known_cause);
  const [supportingSignals, setSupportingSignals] = useState(
    toLines(groundTruth.supporting_signals)
  );
  const [distractors, setDistractors] = useState(toLines(groundTruth.distractors));
  const [expectedConsiderations, setExpectedConsiderations] = useState(
    toLines(groundTruth.expected_considerations)
  );
  const [acceptableConclusions, setAcceptableConclusions] = useState(
    toLines(groundTruth.acceptable_conclusions)
  );
  const [unacceptableConclusions, setUnacceptableConclusions] = useState(
    toLines(groundTruth.unacceptable_conclusions)
  );
  const [uncertainty, setUncertainty] = useState(groundTruth.uncertainty);
  const [isSaving, setIsSaving] = useState(false);

  async function handleSave() {
    setIsSaving(true);
    try {
      const response = await fetch(`/api/scenarios/${id}/ground-truth`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          known_cause: knownCause,
          supporting_signals: fromLines(supportingSignals),
          distractors: fromLines(distractors),
          expected_considerations: fromLines(expectedConsiderations),
          acceptable_conclusions: fromLines(acceptableConclusions),
          unacceptable_conclusions: fromLines(unacceptableConclusions),
          uncertainty,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(typeof body.detail === "string" ? body.detail : "Could not save");
        return;
      }
      toast.success("Ground truth saved");
      router.refresh();
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Edit narrative</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2">
          <Label htmlFor="known_cause">Known cause</Label>
          <Textarea
            id="known_cause"
            rows={3}
            value={knownCause}
            onChange={(e) => setKnownCause(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="supporting_signals">Supporting signals (one per line)</Label>
          <Textarea
            id="supporting_signals"
            rows={3}
            value={supportingSignals}
            onChange={(e) => setSupportingSignals(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="distractors">Distractors (one per line)</Label>
          <Textarea
            id="distractors"
            rows={3}
            value={distractors}
            onChange={(e) => setDistractors(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="expected_considerations">Expected considerations (one per line)</Label>
          <Textarea
            id="expected_considerations"
            rows={3}
            value={expectedConsiderations}
            onChange={(e) => setExpectedConsiderations(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="acceptable_conclusions">Acceptable conclusions (one per line)</Label>
          <Textarea
            id="acceptable_conclusions"
            rows={3}
            value={acceptableConclusions}
            onChange={(e) => setAcceptableConclusions(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="unacceptable_conclusions">Unacceptable conclusions (one per line)</Label>
          <Textarea
            id="unacceptable_conclusions"
            rows={3}
            value={unacceptableConclusions}
            onChange={(e) => setUnacceptableConclusions(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="uncertainty">Uncertainty</Label>
          <Textarea
            id="uncertainty"
            rows={2}
            value={uncertainty}
            onChange={(e) => setUncertainty(e.target.value)}
          />
        </div>
        <Button onClick={handleSave} disabled={isSaving}>
          {isSaving ? "Saving…" : "Save narrative"}
        </Button>
      </CardContent>
    </Card>
  );
}
