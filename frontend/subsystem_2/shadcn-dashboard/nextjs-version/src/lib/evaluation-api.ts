import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 34: server-side proxy for Unit 25's evaluation/adaptive-difficulty
 * routes (app/api/evaluation.py) and Unit 26's human-review and portfolio
 * routes (same file's bottom half, plus app/api/portfolio.py) - same
 * shape as src/lib/scenario-api.ts. Every route proxied here is
 * require_admin on the backend (ER-5: evaluation/tier data stays hidden
 * from the Analyst outside the monthly reveal) - this app is Builder-only
 * end to end (PRD Appendix D.2's own "repurposed as the Builder's side"
 * note), so that's a property of who logs into this app, not something
 * this proxy re-checks.
 */
async function evaluationFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return Response.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) {
    return Response.json({ detail: "Server is not configured" }, { status: 500 });
  }

  return fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });
}

export function getEvaluation(threadId: string): Promise<Response> {
  return evaluationFetch(`/api/v1/evaluations/threads/${encodeURIComponent(threadId)}`);
}

export function getHumanReview(threadId: string): Promise<Response> {
  return evaluationFetch(
    `/api/v1/evaluations/threads/${encodeURIComponent(threadId)}/human-review`
  );
}

export function submitHumanReview(threadId: string, body: unknown): Promise<Response> {
  return evaluationFetch(
    `/api/v1/evaluations/threads/${encodeURIComponent(threadId)}/human-review`,
    { method: "POST", body: JSON.stringify(body) }
  );
}

export function getPortfolioExport(threadId: string): Promise<Response> {
  return evaluationFetch(`/api/v1/portfolio/threads/${encodeURIComponent(threadId)}`);
}
