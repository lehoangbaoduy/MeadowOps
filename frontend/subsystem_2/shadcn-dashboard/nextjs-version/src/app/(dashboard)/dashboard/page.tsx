import { LayoutDashboard } from "lucide-react"

import { listNotificationFeed } from "@/lib/chat-api"
import { NotificationsPanel } from "./components/notifications-panel"
import type { NotificationFeedItem } from "../mail/data"

// Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): Notifications is wired to the
// real API; Open Work / Company Status / Completed Work stay the
// pre-existing stub until their own change. Unit 39: the Notifications
// section reads the notification feed (deadlines + unread Analyst replies).
export default async function DashboardPage() {
  const feedResponse = await listNotificationFeed()
  // A non-2xx used to render identically to "no notifications" with no trace
  // of why - logging server-side at least makes an auth/backend failure
  // diagnosable instead of looking like an empty inbox.
  if (!feedResponse.ok) {
    console.error("Failed to load notification feed:", feedResponse.status)
  }
  const feed: NotificationFeedItem[] = feedResponse.ok ? await feedResponse.json() : []

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
        <NotificationsPanel items={feed} />
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
