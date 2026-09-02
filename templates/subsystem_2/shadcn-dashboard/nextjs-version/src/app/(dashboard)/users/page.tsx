import { Users } from "lucide-react"

export default function UsersPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Users</h1>
        <p className="text-muted-foreground">
          Repurposed table pattern — scenario/portfolio history and the SQL query-history admin view (6.12).
        </p>
      </div>
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-16 text-center">
        <Users className="size-8 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">No records yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          History appears here once this view is wired to the real API layer.
        </p>
      </div>
    </div>
  )
}
