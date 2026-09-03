import { listOpenExceptions } from "@/lib/scenario-api";

import { CreateScenarioForm } from "./components/create-scenario-form";
import type { ExceptionFlag } from "../types";

export default async function NewScenarioPage() {
  const response = await listOpenExceptions();
  const exceptions: ExceptionFlag[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">New Scenario</h1>
        <p className="text-muted-foreground">
          Select an open exception to seed the scenario&apos;s evidence package, then set its
          type, competency, and difficulty.
        </p>
      </div>
      <CreateScenarioForm exceptions={exceptions} />
    </div>
  );
}
