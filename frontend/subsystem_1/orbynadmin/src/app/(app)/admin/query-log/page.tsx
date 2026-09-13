import { PageHeader } from "@/components/page-header";
import { AdminQueryLogTable, type AdminQueryLogEntry } from "@/components/admin-query-log-table";
import { getAdminQueryLog } from "@/lib/admin-api";
import { getCurrentRole } from "@/lib/current-user";

/**
 * Unit 28 (MEADOWOPS-API-005, PRD 6.12/S1-FR-14): admin cross-user view of
 * Query Playground activity — "framed and used as a coaching signal, not a
 * surveillance one" (PRD 328, Principle 7). AppSidebar (Unit 28) already
 * hides the nav entry from the Analyst role, but that's cosmetic — the real
 * boundary is the backend's require_admin (app.core.auth) on
 * GET /api/v1/admin/query-log. Checking the role again here, rather than
 * just forwarding whatever the backend's 403 produces, means an Analyst who
 * navigates here directly sees a clean "no access" message.
 *
 * getCurrentRole() returns null both for "not an admin" and for an
 * unrelated infra failure (missing cookie, unreachable backend) — same
 * collapsed contract every other page using it already accepts (Unit 17a).
 * A transient failure here reads as "no access" rather than a distinct
 * error state, same as `response.ok ? await response.json() : []` below
 * reads a fetch failure as "no rows" — both match the existing pattern in
 * every other admin list page (e.g. settings/products/page.tsx), not a
 * gap specific to this one.
 */
export default async function AdminQueryLogPage() {
  const role = await getCurrentRole();
  if (role !== "admin") {
    return (
      <div className="space-y-6">
        <PageHeader title="Query Log" />
        <p className="text-sm text-muted-foreground">
          You don&apos;t have access to this page.
        </p>
      </div>
    );
  }

  const response = await getAdminQueryLog(500, 0);
  const rows: AdminQueryLogEntry[] = response.ok ? await response.json() : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Query Log"
        description="Every query submitted through the Query page, across all users — a coaching signal, not a surveillance one."
      />
      <AdminQueryLogTable initialData={rows} />
    </div>
  );
}
