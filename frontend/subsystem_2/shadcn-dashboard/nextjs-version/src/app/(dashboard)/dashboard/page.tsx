import { listNotificationFeed, listThreads } from "@/lib/chat-api"
import { getExecutiveSummary, listScenarios } from "@/lib/scenario-api"
import { CompanyStatus, type ExecutiveSummary } from "./components/company-status"
import { NotificationsPanel } from "./components/notifications-panel"
import { WorkList } from "./components/work-list"
import type { ChatThread, NotificationFeedItem } from "../mail/data"

// Unit 39 (PRD 6.1): every section is read from the real API. A failed read
// is logged server-side and renders as that section's empty state, so an
// auth/backend problem is diagnosable instead of looking like "no work".
async function readJson<T>(response: Response, what: string, fallback: T): Promise<T> {
  if (!response.ok) {
    console.error(`Failed to load ${what}:`, response.status)
    return fallback
  }
  return (await response.json()) as T
}

export default async function DashboardPage() {
  const [feedResponse, threadsResponse, scenariosResponse, executiveResponse] = await Promise.all([
    listNotificationFeed(),
    listThreads(),
    listScenarios(),
    getExecutiveSummary(),
  ])
  const feed = await readJson<NotificationFeedItem[]>(feedResponse, "notification feed", [])
  const threads = await readJson<ChatThread[]>(threadsResponse, "threads", [])
  const scenarios = await readJson<{ id: string; title: string; status: string }[]>(
    scenariosResponse,
    "scenarios",
    []
  )
  const executive = await readJson<ExecutiveSummary | null>(
    executiveResponse,
    "company status",
    null
  )
  const scenarioTitles = Object.fromEntries(scenarios.map((s) => [s.id, s.title]))
  // A removed (cancelled) scenario's chats are kept as history but are not
  // work anyone has to do, so they stay out of Open Work.
  const cancelledScenarioIds = new Set(
    scenarios.filter((s) => s.status === "cancelled").map((s) => s.id)
  )
  const openThreads = threads.filter(
    (thread) => thread.status !== "completed" && !cancelledScenarioIds.has(thread.scenario_id)
  )
  const completedThreads = threads.filter((thread) => thread.status === "completed")

  return (
    <div className="space-y-8 px-4 lg:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Home</h1>
        <p className="text-muted-foreground">
          Open Work, Company Status, Notifications and Completed Work.
        </p>
      </div>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Notifications</h2>
        <NotificationsPanel items={feed} />
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Open Work</h2>
        <WorkList
          variant="open"
          threads={openThreads}
          scenarioTitles={scenarioTitles}
          emptyMessage="No open conversations. Start one from Chat on an active scenario."
        />
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Company Status</h2>
        <CompanyStatus summary={executive} />
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Completed Work</h2>
        <WorkList
          variant="completed"
          threads={completedThreads}
          scenarioTitles={scenarioTitles}
          emptyMessage="No completed conversations yet."
        />
      </section>
    </div>
  )
}
