import { NextRequest, NextResponse } from "next/server";

import { acceptDecision } from "@/lib/ledger-api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const payload = await request.json().catch(() => ({}));
  const response = await acceptDecision(id, payload?.approval_authority);
  return NextResponse.json(await response.json(), { status: response.status });
}
