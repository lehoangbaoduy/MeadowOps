import { NextResponse } from "next/server";

import { getEvaluation } from "@/lib/evaluation-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await getEvaluation(id);
  return NextResponse.json(await response.json(), { status: response.status });
}
