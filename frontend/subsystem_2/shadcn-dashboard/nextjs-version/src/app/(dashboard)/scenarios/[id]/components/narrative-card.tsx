import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import type { ScenarioStatus } from "../../types";
import { RegenerateButton } from "./regenerate-button";

/**
 * Unit 39 (MEADOWOPS-DOM-027): the plain-language story of the scenario, for
 * the Builder. Free text rendered as a plain JSX text node (React escapes
 * it), whitespace-preserved so paragraphs survive. Regenerable on any
 * scenario that is not cancelled.
 */
export function NarrativeCard({
  id,
  narrative,
  status,
}: {
  id: string;
  narrative: string;
  status: ScenarioStatus;
}) {
  const canRegenerate = status !== "cancelled";
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">Scenario narrative</CardTitle>
          <Badge variant="secondary">Builder only</Badge>
          {canRegenerate && (
            <div className="ml-auto">
              <RegenerateButton
                id={id}
                action="regenerate-narrative"
                noun="narrative"
                hasExisting={narrative !== ""}
              />
            </div>
          )}
        </div>
        <CardDescription>What is going on in this scenario, in plain language.</CardDescription>
      </CardHeader>
      <CardContent>
        {narrative ? (
          <p className="max-w-prose text-sm leading-relaxed whitespace-pre-wrap">{narrative}</p>
        ) : (
          <p className="text-sm italic text-muted-foreground">
            {canRegenerate
              ? "No narrative yet. Generate one, or write your own."
              : "No narrative was recorded for this scenario."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
