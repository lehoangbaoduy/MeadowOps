import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

import { personaLabel, type ScenarioThread } from "../thread-types";
import { EvaluationPanel } from "./evaluation-panel";

/**
 * Unit 34: the evaluation/human-review/portfolio surface for a scenario's
 * persona threads - chat_thread is unique on (scenario_id, persona), not
 * (scenario_id), so a scenario can genuinely have several threads (one
 * per persona the Builder opened); each gets its own independent
 * EvaluationPanel rather than this page assuming a single thread.
 */
export function ScenarioThreads({ threads }: { threads: ScenarioThread[] }) {
  if (threads.length === 0) {
    return null;
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Persona threads</h2>
      {threads.map((thread) => (
        <Card key={thread.id}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {personaLabel(thread.persona)}
              <Badge variant={thread.status === "completed" ? "default" : "outline"}>
                {thread.status === "completed" ? "Completed" : "Open"}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <EvaluationPanel threadId={thread.id} threadStatus={thread.status} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
