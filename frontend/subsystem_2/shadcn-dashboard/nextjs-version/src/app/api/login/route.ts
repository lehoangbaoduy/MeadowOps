import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 20a (MEADOWOPS-UI-002): posts email+password to the FastAPI
 * backend's real login endpoint — the backend is the only place that ever
 * sees a password or verifies one, same as orbynadmin's own `/api/login`
 * (Unit 17a). This app is admin-only (PRD 8.4/DD-24 point 4: every
 * scenario route it drives is `require_admin`), so the role returned in
 * the backend's own `LoginResponse` (`{access_token, role}`) is checked
 * right here, synchronously, *before* the session cookie is ever set —
 * pre-implementation security review of this unit (CRITICAL finding):
 * setting the cookie first and clearing it afterward on a client-side
 * role check is not real enforcement, since anything that reaches this
 * route without running that follow-up check (a direct POST, a second
 * tab, a network blip) walks away with a valid cookie the role check
 * never ran on. Failing closed here means no such window ever opens.
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

  const { access_token: token, role } = await backendResponse.json();
  if (role !== "admin") {
    return NextResponse.json(
      { detail: "This workspace is available to Builder (admin) accounts only" },
      { status: 401 }
    );
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
  });
  return response;
}
