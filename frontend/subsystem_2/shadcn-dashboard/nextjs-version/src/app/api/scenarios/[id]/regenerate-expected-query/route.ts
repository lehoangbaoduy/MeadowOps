import { NextResponse } from "next/server";

import { regenerateExpectedQuery } from "@/lib/scenario-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await regenerateExpectedQuery(id);
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status });
}
