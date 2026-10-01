import { NextResponse } from "next/server";

import { getSandboxSchema } from "@/lib/admin-api";

export async function GET(): Promise<NextResponse> {
  const response = await getSandboxSchema();
  return NextResponse.json(await response.json(), { status: response.status });
}
