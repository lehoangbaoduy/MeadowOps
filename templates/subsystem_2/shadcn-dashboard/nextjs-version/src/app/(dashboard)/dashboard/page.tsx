import { LayoutDashboard } from "lucide-react"

export default function DashboardPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Home</h1>
        <p className="text-muted-foreground">
          Open Work, Company Status, Notifications and Completed Work.
        </p>
      </div>
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-16 text-center">
        <LayoutDashboard className="size-8 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">No work items yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Open Work and Company Status appear here once this view is wired to the real API layer.
        </p>
      </div>
    </div>
  )
}
