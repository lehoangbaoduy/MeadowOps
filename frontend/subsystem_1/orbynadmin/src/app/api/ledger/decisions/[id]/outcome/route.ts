import { NextRequest, NextResponse } from "next/server";

import { recordOutcome } from "@/lib/ledger-api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const payload = await request.json();
  const response = await recordOutcome(id, payload.outcome, payload.notes ?? null);
  return NextResponse.json(await response.json(), { status: response.status });
}
