import { NextRequest, NextResponse } from "next/server";

import { getHumanReview, submitHumanReview } from "@/lib/evaluation-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await getHumanReview(id);
  return NextResponse.json(await response.json(), { status: response.status });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const payload = await request.json();
  const response = await submitHumanReview(id, payload);
  return NextResponse.json(await response.json(), { status: response.status });
}
