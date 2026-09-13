/**
 * Unit 30b (MEADOWOPS-UI-004, PRD 6.1 "Drafting" bullet, catalog row 31,
 * B12 follow-on to U30): a browser-local buffer in front of the server-
 * persisted draft (app.services.chat.save_draft, proxied via
 * /api/chat/threads/[id]/draft). localStorage writes need no network -
 * this buffer is what actually protects typed text against a network
 * interruption; syncDraftToServer is the periodic best-effort sync that
 * gives PRD 6.1's "saved... indefinitely" cross-session durability.
 */
const STORAGE_PREFIX = "meadowops:composer-draft:";

function storageKey(threadId: string): string {
  return `${STORAGE_PREFIX}${threadId}`;
}

// Every localStorage access is wrapped — private browsing, a full quota,
// or storage disabled by policy all throw, and none of those should ever
// crash the composer, just degrade to in-memory-only (this feature's own
// pre-existing behavior).
//
// Code review (this unit, HIGH): returns `string | null`, not `string` —
// `null` means "no buffer was ever saved for this thread," distinct from
// `""`, which means "the user deliberately cleared their draft text."
// Collapsing those (the original version returned "" for both) made a
// just-cleared draft indistinguishable from an unwritten one, so the
// restore-on-thread-open logic in thread-view.tsx would fall through to
// whatever stale draft_body the server still had and silently resurrect
// text the user had just deleted.
export function loadDraftBuffer(threadId: string): string | null {
  try {
    return window.localStorage.getItem(storageKey(threadId));
  } catch {
    return null;
  }
}

export function saveDraftBuffer(threadId: string, body: string): void {
  try {
    window.localStorage.setItem(storageKey(threadId), body);
  } catch {
    // degrade to in-memory-only
  }
}

export function clearDraftBuffer(threadId: string): void {
  try {
    window.localStorage.removeItem(storageKey(threadId));
  } catch {
    // degrade to in-memory-only
  }
}

// Security review (this unit, HIGH): the buffer above is keyed by
// thread_id only, not by user - correct for the collision the draft
// table itself guards against (two different roles' drafts on the same
// thread never share a row server-side), but on a shared browser, a
// leftover buffer from whoever was last logged in would otherwise
// silently pre-fill the next person's composer, since it's preferred
// over the correctly per-user-scoped server value. Called from
// nav-user.tsx's log-out handler in both subsystems, so no stale draft
// ever survives a session boundary on shared hardware — a real scenario
// at this project's own scale (Admin/Builder and Analyst share the same
// login page, S1-FR-16).
export function clearAllDraftBuffers(): void {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && key.startsWith(STORAGE_PREFIX)) keys.push(key);
    }
    keys.forEach((key) => window.localStorage.removeItem(key));
  } catch {
    // degrade to in-memory-only
  }
}

// Best-effort — a failed sync leaves the localStorage buffer above as the
// only copy, tried again on the next debounced keystroke or the next time
// this thread is opened. `signal` lets a caller (thread-view.tsx) cancel
// an in-flight sync — code review (this unit, HIGH): without this, a sync
// already on the wire when the user hits Send could still land at the
// server *after* send_message's own transactional draft-clear, silently
// resurrecting the just-sent text as a stale draft next time this thread
// loads. Aborting narrows that race to the (much smaller, effectively
// negligible for this project's scale) window between the debounce timer
// firing and the abort call actually reaching the connection.
export async function syncDraftToServer(
  threadId: string,
  body: string,
  signal?: AbortSignal
): Promise<void> {
  try {
    await fetch(`/api/chat/threads/${threadId}/draft`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
      signal,
    });
  } catch {
    // network failure or deliberate abort — see above
  }
}
