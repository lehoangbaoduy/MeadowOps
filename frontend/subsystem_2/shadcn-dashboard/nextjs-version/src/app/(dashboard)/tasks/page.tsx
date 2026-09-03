import { CheckSquare } from "lucide-react"

export default function TasksPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Scenario Builder</h1>
        <p className="text-muted-foreground">
          Select, preview, edit, and approve work scenarios for the Analyst (PRD 6.4).
        </p>
      </div>
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-16 text-center">
        <CheckSquare className="size-8 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">Not wired to the backend yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Unit 18 (MEADOWOPS-DOM-011) shipped the backend — Scenario model, state
          machine, and admin-only /api/v1/admin/scenarios endpoints — but this
          page stays an empty-state stub until Unit 20 establishes how Subsystem
          2 authenticates and talks to the API at all (this template currently
          has no login flow or API client of any kind, unlike Subsystem 1).
        </p>
      </div>
    </div>
  )
}
