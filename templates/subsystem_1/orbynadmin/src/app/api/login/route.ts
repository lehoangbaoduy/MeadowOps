import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";
import { timingSafeTokenEquals } from "@/lib/token-compare";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const expected = process.env.MEADOWOPS_BUILDER_TOKEN;
  if (!expected) {
    // Fails fast/loud rather than a confusing "invalid credentials" — this
    // is a misconfigured deployment, not a bad login attempt.
    return NextResponse.json({ detail: "Server is not configured" }, { status: 500 });
  }

  let token: unknown;
  try {
    ({ token } = await request.json());
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  if (typeof token !== "string" || !timingSafeTokenEquals(token, expected)) {
    return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
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
