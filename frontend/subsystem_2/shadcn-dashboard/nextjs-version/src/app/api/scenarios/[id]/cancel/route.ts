import { NextResponse } from "next/server";

import { cancelScenario } from "@/lib/scenario-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await cancelScenario(id);
  return NextResponse.json(await response.json(), { status: response.status });
}
