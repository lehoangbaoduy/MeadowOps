import Link from "next/link";
import { ClipboardList, Plus } from "lucide-react";

import { listScenarios } from "@/lib/scenario-api";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { ScenarioStatusBadge } from "./components/status-badge";
import {
  COMPETENCY_CLUSTER_OPTIONS,
  DIFFICULTY_TIER_OPTIONS,
  SCENARIO_TYPE_OPTIONS,
  type Scenario,
  type ScenarioStatus,
} from "./types";

const STATUS_FILTERS: { value: ScenarioStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "approved", label: "Approved" },
  { value: "active", label: "Active" },
  { value: "cancelled", label: "Cancelled" },
];

function label(options: { value: string; label: string }[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value;
}

export default async function ScenariosPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const filter = status && status !== "all" ? status : undefined;

  const response = await listScenarios(filter);
  const scenarios: Scenario[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold tracking-tight">Scenarios</h1>
          <p className="text-muted-foreground">
            Builder controls for the Analyst work simulation engine (PRD 6.4) — select an
            exception, inject it as a scenario, and take it through draft → approved → active.
          </p>
        </div>
        <Button asChild>
          <Link href="/scenarios/new">
            <Plus className="size-4" />
            New Scenario
          </Link>
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={f.value}
            asChild
            variant={filter === f.value || (!filter && f.value === "all") ? "default" : "outline"}
            size="sm"
          >
            <Link href={f.value === "all" ? "/scenarios" : `/scenarios?status=${f.value}`}>
              {f.label}
            </Link>
          </Button>
        ))}
      </div>

      {scenarios.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-16 text-center">
          <ClipboardList className="size-8 text-muted-foreground opacity-50" />
          <p className="text-sm font-medium">No scenarios yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Create one from an open exception to get started.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Competency</TableHead>
                <TableHead>Difficulty</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scenarios.map((scenario) => (
                <TableRow key={scenario.id}>
                  <TableCell className="font-medium">
                    <Link href={`/scenarios/${scenario.id}`} className="hover:underline">
                      {scenario.title}
                    </Link>
                  </TableCell>
                  <TableCell>{label(SCENARIO_TYPE_OPTIONS, scenario.scenario_type)}</TableCell>
                  <TableCell>
                    {label(COMPETENCY_CLUSTER_OPTIONS, scenario.competency_cluster)}
                  </TableCell>
                  <TableCell>{label(DIFFICULTY_TIER_OPTIONS, scenario.difficulty_tier)}</TableCell>
                  <TableCell>
                    <ScenarioStatusBadge status={scenario.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(scenario.created_at).toLocaleDateString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
