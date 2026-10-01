import { NextResponse } from "next/server";

import { getRepopulateStatus } from "@/lib/scenario-api";

export async function GET(): Promise<NextResponse> {
  const response = await getRepopulateStatus();
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status });
}
