import { LayoutDashboard } from "lucide-react"

import { listNotifications, listThreads } from "@/lib/chat-api"
import { NotificationsPanel } from "./components/notifications-panel"
import type { ChatThread, Notification } from "../mail/data"

// Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): only the Notifications section
// is wired to the real API here — Open Work / Company Status / Completed
// Work stay the pre-existing stub (deferred to a later unit, per this
// template's CLAUDE.md) since this unit's chartered scope is chat
// notifications + deadline tracking only.
export default async function DashboardPage() {
  const [notificationsResponse, threadsResponse] = await Promise.all([
    listNotifications(),
    listThreads(),
  ])
  // Security review (this unit): a non-2xx here used to render identically
  // to "no notifications" with no trace of why — for a feed whose entire
  // purpose is surfacing missed deadlines, that's the wrong failure mode
  // to fail silently into. Logging server-side at least makes an
  // auth/backend failure diagnosable instead of looking like an empty inbox.
  if (!notificationsResponse.ok) {
    console.error("Failed to load notifications:", notificationsResponse.status)
  }
  if (!threadsResponse.ok) {
    console.error("Failed to load threads:", threadsResponse.status)
  }
  const notifications: Notification[] = notificationsResponse.ok
    ? await notificationsResponse.json()
    : []
  const threads: ChatThread[] = threadsResponse.ok ? await threadsResponse.json() : []
  const threadsById = Object.fromEntries(threads.map((thread) => [thread.id, thread]))

  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Home</h1>
        <p className="text-muted-foreground">
          Open Work, Company Status, Notifications and Completed Work.
        </p>
      </div>
      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Notifications</h2>
        <NotificationsPanel notifications={notifications} threadsById={threadsById} />
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
