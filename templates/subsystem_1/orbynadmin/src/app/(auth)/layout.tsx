import Link from "next/link";
import { IconSparkles } from "@tabler/icons-react";

export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <Link href="/dashboard" className="flex items-center gap-2 font-semibold">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <IconSparkles className="size-5" />
          </div>
          OrbynAdmin
        </Link>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </div>

      <div className="relative hidden overflow-hidden bg-zinc-950 lg:block">
        <div
          className="absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(120% 120% at 100% 0%, var(--chart-1) 0%, transparent 45%), radial-gradient(120% 120% at 0% 100%, var(--chart-5) 0%, transparent 45%)",
          }}
        />
        <div className="absolute inset-0 opacity-[0.15] [background-image:linear-gradient(to_right,white_1px,transparent_1px),linear-gradient(to_bottom,white_1px,transparent_1px)] [background-size:44px_44px]" />
        <div className="relative flex h-full flex-col justify-center p-12 text-white">
          <p className="text-2xl font-medium leading-snug tracking-tight">
            MeadowOps — Control Tower
          </p>
        </div>
      </div>
    </div>
  );
}
