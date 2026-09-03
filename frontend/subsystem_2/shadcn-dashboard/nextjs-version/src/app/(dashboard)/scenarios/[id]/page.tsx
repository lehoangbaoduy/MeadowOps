import { notFound } from "next/navigation";

import { getScenario } from "@/lib/scenario-api";

import { ScenarioStatusBadge } from "../components/status-badge";
import {
  COMPETENCY_CLUSTER_OPTIONS,
  DIFFICULTY_TIER_OPTIONS,
  SCENARIO_TYPE_OPTIONS,
  type Scenario,
} from "../types";
import { GroundTruthEditForm } from "./components/ground-truth-edit-form";
import { GroundTruthPreview } from "./components/ground-truth-preview";
import { ScenarioActions } from "./components/scenario-actions";

function label(options: { value: string; label: string }[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value;
}

export default async function ScenarioDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const response = await getScenario(id);
  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    throw new Error("Could not load scenario");
  }
  const scenario: Scenario = await response.json();

  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">{scenario.title}</h1>
            <ScenarioStatusBadge status={scenario.status} />
          </div>
          <p className="text-muted-foreground">
            {label(SCENARIO_TYPE_OPTIONS, scenario.scenario_type)} ·{" "}
            {label(COMPETENCY_CLUSTER_OPTIONS, scenario.competency_cluster)} ·{" "}
            {label(DIFFICULTY_TIER_OPTIONS, scenario.difficulty_tier)}
          </p>
        </div>
        <ScenarioActions id={scenario.id} status={scenario.status} />
      </div>

      <GroundTruthPreview groundTruth={scenario.ground_truth} />

      {scenario.status === "draft" && (
        <GroundTruthEditForm id={scenario.id} groundTruth={scenario.ground_truth} />
      )}
    </div>
  );
}
