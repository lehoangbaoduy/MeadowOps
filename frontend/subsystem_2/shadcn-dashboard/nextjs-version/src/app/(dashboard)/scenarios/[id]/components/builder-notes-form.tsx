"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import type { ScenarioGroundTruth } from "../../types";

// FastAPI answers a plain failure with a string `detail` and a field
// validation failure (e.g. an expected query that is not a single SELECT)
// with a list of {msg} objects.
function errorDetail(body: { detail?: unknown }): string {
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    const message = body.detail
      .map((item) => (item && typeof item.msg === "string" ? item.msg : null))
      .find((msg): msg is string => msg !== null);
    if (message) return message.replace(/^Value error, /, "");
  }
  return "Could not save";
}

/**
 * Unit 39: once a scenario leaves draft the graded fields are locked, but the
 * two Builder-only notes (narrative, expected query) stay editable - the
 * backend accepts a notes-only PATCH for approved/active scenarios. Sends only
 * those two keys so nothing else can be touched from here.
 */
export function BuilderNotesForm({
  id,
  groundTruth,
}: {
  id: string;
  groundTruth: ScenarioGroundTruth;
}) {
  const router = useRouter();
  const [narrative, setNarrative] = useState(groundTruth.narrative ?? "");
  const [expectedQuery, setExpectedQuery] = useState(groundTruth.expected_query ?? "");
  const [isSaving, setIsSaving] = useState(false);

  async function handleSave() {
    setIsSaving(true);
    try {
      const response = await fetch(`/api/scenarios/${id}/ground-truth`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ narrative, expected_query: expectedQuery }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(errorDetail(body));
        return;
      }
      toast.success("Notes saved");
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
        <CardTitle className="text-base">Edit Builder notes</CardTitle>
        <CardDescription>
          The graded fields are locked now that the scenario is no longer a draft. The narrative
          and expected query can still be changed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2">
          <Label htmlFor="notes_narrative">Scenario narrative (Builder only)</Label>
          <Textarea
            id="notes_narrative"
            rows={5}
            value={narrative}
            onChange={(e) => setNarrative(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="notes_expected_query">Expected query (Builder only)</Label>
          <Textarea
            id="notes_expected_query"
            rows={6}
            className="font-mono text-xs"
            spellCheck={false}
            value={expectedQuery}
            onChange={(e) => setExpectedQuery(e.target.value)}
          />
          <p className="text-muted-foreground text-xs">
            One read-only SELECT against the sandbox. Leave empty for none.
          </p>
        </div>
        <Button onClick={handleSave} disabled={isSaving}>
          {isSaving ? "Saving…" : "Save notes"}
        </Button>
      </CardContent>
    </Card>
  );
}
