import type { Metadata } from "next";
import { IconMapPinQuestion } from "@tabler/icons-react";

import { ErrorState } from "@/components/error-state";

export const metadata: Metadata = {
  title: "Page not found",
  description: "The page you were looking for could not be found.",
};

export default function NotFoundExamplePage() {
  return (
    <ErrorState
      code="404"
      title="Page not found"
      description="The page you're looking for doesn't exist or may have been moved. Check the address, or head back to your dashboard to keep going."
      icon={IconMapPinQuestion}
    />
  );
}
