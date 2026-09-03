import { NextResponse } from "next/server";

import { refreshSandbox } from "@/lib/admin-api";

export async function POST(): Promise<NextResponse> {
  const response = await refreshSandbox();
  return NextResponse.json(await response.json(), { status: response.status });
}
