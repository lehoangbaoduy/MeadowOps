import { listThreads } from "@/lib/chat-api"
import { listScenarios } from "@/lib/scenario-api"
import { Mail } from "./components/mail"
import type { ChatThread, ScenarioOption } from "./data"

export default async function MailPage() {
  const [threadsResponse, scenariosResponse] = await Promise.all([
    listThreads(),
    // Chatting only makes sense once a scenario is actually in play
    // (Appendix C's walkthrough) — draft/approved/cancelled scenarios
    // aren't offered in the "New thread" picker.
    listScenarios("active"),
  ])
  const threads: ChatThread[] = threadsResponse.ok ? await threadsResponse.json() : []
  const scenarios: ScenarioOption[] = scenariosResponse.ok
    ? (await scenariosResponse.json()).map((s: { id: string; title: string }) => ({
        id: s.id,
        title: s.title,
      }))
    : []

  return (
    <div className="@container/main flex flex-1 flex-col">
      <div className="h-[calc(100vh-4rem)] px-4 md:px-6">
        <Mail threads={threads} scenarios={scenarios} defaultLayout={[32, 68]} />
      </div>
    </div>
  )
}
