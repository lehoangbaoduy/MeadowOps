import { CheckSquare } from "lucide-react"

export default function TasksPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Tasks</h1>
        <p className="text-muted-foreground">
          Kanban view of work-queue states (PRD 6.1).
        </p>
      </div>
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-16 text-center">
        <CheckSquare className="size-8 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">Optional, deprioritized — not built</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          The PRD lists this drag-and-drop kanban view as optional
          ("Priority 3 — cut first," PRD line 579/680) and it was never
          required for Done, so it stays a stub. This page previously
          described itself as the Scenario Builder awaiting an auth/API
          layer that didn't exist yet — that was stale even when written:
          the real Scenario Builder (Unit 18/20a) shipped in the same
          commit and lives at {" "}
          <a href="/scenarios" className="underline">
            /scenarios
          </a>
          , with its own login flow and API client, both long since working.
        </p>
      </div>
    </div>
  )
}
