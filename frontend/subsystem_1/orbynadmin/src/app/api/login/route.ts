import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 17a (MEADOWOPS-DOM-010, PRD 5.1/8.4 amendment, DD-22): posts
 * email+password to the FastAPI backend's real login endpoint instead of
 * comparing a single shared Builder token — the backend is the only place
 * that ever sees a password hash or verifies one. On success, the signed
 * session token it returns becomes this cookie's value (same httpOnly
 * cookie as before; the browser never holds it directly either way).
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) {
    return NextResponse.json({ detail: "Server is not configured" }, { status: 500 });
  }

  let email: unknown;
  let password: unknown;
  try {
    ({ email, password } = await request.json());
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  if (typeof email !== "string" || typeof password !== "string") {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  const backendResponse = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  if (!backendResponse.ok) {
    const body = await backendResponse.json().catch(() => ({}));
    return NextResponse.json(
      { detail: body.detail ?? "Sign in failed" },
      { status: backendResponse.status === 429 ? 429 : 401 }
    );
  }

  const { access_token: token } = await backendResponse.json();
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
  });
  return response;
}
