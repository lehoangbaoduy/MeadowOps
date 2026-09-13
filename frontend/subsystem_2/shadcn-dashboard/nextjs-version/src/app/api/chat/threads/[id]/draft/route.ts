import { NextRequest, NextResponse } from "next/server";

import { saveDraft } from "@/lib/chat-api";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  // Security review (Unit 30b, LOW): malformed JSON in the request body
  // used to throw here uncaught, surfacing as an unhandled 500 instead of
  // a clean 400 — not exploitable (the backend still validates via
  // DraftUpdate either way), just a robustness gap.
  let payload: { body?: unknown };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  // A missing/non-string body is rejected rather than silently coerced to
  // "" — treating a malformed payload as "clear my draft" would be a
  // surprising, hard-to-notice footgun.
  if (typeof payload.body !== "string") {
    return NextResponse.json({ detail: "body must be a string" }, { status: 400 });
  }
  const response = await saveDraft(id, payload.body);
  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  return NextResponse.json(await response.json(), { status: response.status });
}
