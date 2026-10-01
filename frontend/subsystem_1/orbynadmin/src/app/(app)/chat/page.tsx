import { PageHeader } from "@/components/page-header";
import { listThreads } from "@/lib/chat-api";
import { getCurrentRole } from "@/lib/current-user";
import { ChatInbox } from "./components/chat-inbox";
import type { ChatThread } from "./types";

export default async function ChatPage() {
  const response = await listThreads();
  const threads: ChatThread[] = response.ok ? await response.json() : [];
  const canDeleteThreads = (await getCurrentRole()) === "admin";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Chat"
        description="Persona threads opened by the Builder for active scenarios."
      />
      <ChatInbox initialThreads={threads} canDeleteThreads={canDeleteThreads} />
    </div>
  );
}
