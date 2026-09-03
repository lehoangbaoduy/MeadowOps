import { CalendarDays } from "lucide-react"

export default function CalendarPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Calendar</h1>
        <p className="text-muted-foreground">
          Response-window deadlines across active scenarios.
        </p>
      </div>
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-16 text-center">
        <CalendarDays className="size-8 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">No deadlines yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Response-window deadlines appear here once this view is wired to the real API layer.
        </p>
      </div>
    </div>
  )
}
