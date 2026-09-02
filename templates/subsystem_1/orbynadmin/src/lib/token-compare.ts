import { timingSafeEqual } from "node:crypto";

/**
 * Unit 8: the session cookie's value IS the real Builder bearer token, not
 * an opaque session id — there is no server-side session store to look one
 * up against (PRD 5.1 scopes this as a two-person tool with a single shared
 * token, not a full identity system). httpOnly is what actually matters
 * here: it keeps the token out of reach of any in-page JS (the realistic
 * XSS-exfiltration threat react/security.md's "never store sessions in
 * localStorage" rule is guarding against), regardless of what the cookie's
 * value happens to be. The Builder already knows their own token, so a
 * physically-present devtools inspection isn't a new exposure.
 */
export function timingSafeTokenEquals(a: string, b: string): boolean {
  const aBuf = Buffer.from(a);
  const bBuf = Buffer.from(b);
  // timingSafeEqual throws on mismatched lengths rather than returning
  // false — same non-constant-time-but-harmless early exit the backend's
  // require_builder accepts (backend/app/core/auth.py), since token length
  // alone reveals nothing an attacker couldn't already guess by trying.
  if (aBuf.length !== bBuf.length) return false;
  return timingSafeEqual(aBuf, bBuf);
}
