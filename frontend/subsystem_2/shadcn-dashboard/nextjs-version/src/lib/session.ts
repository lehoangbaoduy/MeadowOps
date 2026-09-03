/**
 * Unit 20a (MEADOWOPS-UI-002): this app's own session cookie — a fully
 * separate session from orbynadmin's, never shared or SSO'd, even though
 * both apps authenticate against the same FastAPI backend and the same
 * JWT signing key. Deliberately a *different* cookie name than
 * orbynadmin's `meadowops_session`: cookie storage in the browser is
 * scoped by host and path only, not by port, so two Next.js dev servers
 * both running on `localhost` (different ports) would otherwise share one
 * cookie jar — an Analyst already signed into orbynadmin would silently
 * carry a valid cookie straight past this app's login page (pre-
 * implementation security review of this unit, HIGH finding).
 *
 * Kept in its own module, no `node:crypto` import, so it stays safe to
 * import from the Edge-runtime `src/middleware.ts`.
 */
export const SESSION_COOKIE = "meadowops_scenarios_session";
