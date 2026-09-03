/**
 * Just the cookie name — kept in its own module (no `node:crypto` import)
 * because src/proxy.ts imports this and runs in the Edge runtime, which
 * doesn't support Node's crypto module (Next.js build warns loudly if a
 * `node:*` import reaches an Edge bundle). Unit 17a (MEADOWOPS-DOM-010):
 * the cookie's value is now a signed session token verified by the FastAPI
 * backend (app.core.security), not a raw shared token compared in Node —
 * src/lib/token-compare.ts and its Node-runtime timing-safe compare are
 * gone; there is nothing left in this app that verifies the token itself.
 */
export const SESSION_COOKIE = "meadowops_session";
