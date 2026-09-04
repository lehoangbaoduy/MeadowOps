import Link from "next/link";
import { IconSparkles } from "@tabler/icons-react";

export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="bg-muted flex min-h-svh flex-col items-center justify-center gap-6 p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <Link
          href="/dashboard"
          className="flex items-center gap-2 self-center font-semibold"
        >
          <div className="flex size-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <IconSparkles className="size-5" />
          </div>
          MeadowOps
        </Link>
        {children}
      </div>
    </div>
  );
}
