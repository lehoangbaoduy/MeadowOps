/**
 * Just the cookie name — kept in its own module (no `node:crypto` import)
 * because src/middleware.ts imports this and runs in the Edge runtime,
 * which doesn't support Node's crypto module (Next.js build warns loudly
 * if a `node:*` import reaches an Edge bundle). The actual token-comparison
 * logic lives in src/lib/token-compare.ts, used only by the Node-runtime
 * /api/login route handler.
 */
export const SESSION_COOKIE = "meadowops_session";
