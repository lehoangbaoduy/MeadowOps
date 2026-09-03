import { NextResponse } from "next/server";

import { approveScenario } from "@/lib/scenario-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await approveScenario(id);
  return NextResponse.json(await response.json(), { status: response.status });
}
