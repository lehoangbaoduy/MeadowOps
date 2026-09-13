import { NextRequest, NextResponse } from "next/server";

import { getAttachment } from "@/lib/chat-api";

// Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
// unlike every other proxy route in this app, a successful response here
// is binary file content, not JSON - Content-Type/Content-Disposition/
// X-Content-Type-Options are forwarded from the backend's own response
// verbatim (it already set them correctly, app.api.chat.
// get_message_attachment_route) rather than reconstructed here, so there
// is exactly one place that decides what those headers say.
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await getAttachment(id);
  if (!response.ok) {
    return NextResponse.json(await response.json(), { status: response.status });
  }
  const content = await response.arrayBuffer();
  const headers = new Headers();
  const contentType = response.headers.get("content-type");
  const contentDisposition = response.headers.get("content-disposition");
  const nosniff = response.headers.get("x-content-type-options");
  if (contentType) headers.set("Content-Type", contentType);
  if (contentDisposition) headers.set("Content-Disposition", contentDisposition);
  if (nosniff) headers.set("X-Content-Type-Options", nosniff);
  return new NextResponse(content, { status: response.status, headers });
}
