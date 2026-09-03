import { redirect } from "next/navigation";

import { getCurrentRole } from "@/lib/current-user";

import { DashboardShell } from "./dashboard-shell";

/**
 * Unit 20a (MEADOWOPS-UI-002): the real, rejecting enforcement boundary
 * for this admin-only app — re-run on every authenticated page load,
 * regardless of how the cookie arrived (normal login, a stray cookie from
 * another `localhost` app during dev, a restored browser session).
 * `/api/login` already refuses to set the cookie for a non-admin
 * (pre-implementation security review, CRITICAL fix), and this app's
 * middleware only checks cookie *presence* (Edge runtime can't verify a
 * signed token) — this Server Component is what actually calls the
 * backend and rejects anything that isn't a live `admin` session.
 *
 * Redirects to `/api/session-expired`, not `/sign-in` directly (code
 * review, HIGH) — a Server Component can't delete the stale cookie
 * itself during render, so redirecting straight to `/sign-in` left it
 * attached; `middleware.ts` would then see that cookie on `/sign-in` and
 * bounce straight back here, looping forever for any session that
 * outlives its backend-verified JWT.
 */
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const role = await getCurrentRole();
  if (role !== "admin") {
    redirect("/api/session-expired");
  }

  return <DashboardShell>{children}</DashboardShell>;
}
