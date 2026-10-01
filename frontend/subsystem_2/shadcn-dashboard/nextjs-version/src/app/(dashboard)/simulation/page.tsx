import { RepopulatePanel } from "./repopulate-panel";

export default function SimulationPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Simulation</h1>
        <p className="text-muted-foreground">
          Controls for the simulated company the Analyst investigates.
        </p>
      </div>
      <RepopulatePanel />
    </div>
  );
}
