import Link from "next/link";
import {
  IconSparkles,
  IconArrowLeft,
  type TablerIcon,
} from "@tabler/icons-react";

import { Button } from "@/components/ui/button";

export type ErrorStateProps = {
  /** The HTTP status code shown as the large faded hero number. */
  code: string;
  /** Bold headline under the code. */
  title: string;
  /** Muted supporting copy. */
  description: string;
  /** Optional accent icon rendered in a rounded card above the code. */
  icon?: TablerIcon;
  /** Primary action link (defaults to the dashboard). */
  primaryHref?: string;
  primaryLabel?: string;
  /** Optional secondary action link. */
  secondaryHref?: string;
  secondaryLabel?: string;
  /** Optional icon for the secondary action. */
  secondaryIcon?: TablerIcon;
};

export function ErrorState({
  code,
  title,
  description,
  icon: Icon,
  primaryHref = "/dashboard",
  primaryLabel = "Back to dashboard",
  secondaryHref,
  secondaryLabel,
  secondaryIcon: SecondaryIcon,
}: ErrorStateProps) {
  return (
    <div className="relative flex min-h-svh flex-col overflow-hidden bg-background text-foreground">
      {/* Background — subtle grid + soft brand glow, tuned for light & dark */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 [background-image:linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] [background-size:56px_56px] [mask-image:radial-gradient(ellipse_65%_55%_at_50%_35%,black,transparent)]" />
        <div
          className="absolute left-1/2 top-1/3 h-[480px] w-[760px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-25 blur-3xl"
          style={{
            background:
              "radial-gradient(closest-side, var(--chart-1), transparent), radial-gradient(closest-side at 65% 60%, var(--chart-5), transparent)",
          }}
        />
      </div>

      {/* Header — OrbynAdmin wordmark */}
      <header className="flex items-center px-6 py-5">
        <Link
          href="/dashboard"
          className="flex items-center gap-2 font-semibold"
        >
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <IconSparkles className="size-5" />
          </span>
          <span className="tracking-tight">OrbynAdmin</span>
        </Link>
      </header>

      {/* Content */}
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-lg text-center">
          {Icon ? (
            <div className="mx-auto flex size-16 items-center justify-center rounded-2xl border bg-card shadow-sm">
              <Icon className="size-8 text-primary" />
            </div>
          ) : null}

          <p className="mt-8 select-none bg-gradient-to-b from-foreground to-muted-foreground/25 bg-clip-text text-[6.5rem] leading-none font-bold tracking-tighter text-transparent tabular-nums sm:text-[9rem]">
            {code}
          </p>

          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            {title}
          </h1>
          <p className="mx-auto mt-4 max-w-md text-balance text-muted-foreground">
            {description}
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button size="lg" className="h-11 gap-2 px-6 text-sm" asChild>
              <Link href={primaryHref}>
                <IconArrowLeft className="size-4" />
                {primaryLabel}
              </Link>
            </Button>
            {secondaryHref && secondaryLabel ? (
              <Button
                size="lg"
                variant="outline"
                className="h-11 gap-2 px-6 text-sm"
                asChild
              >
                <Link href={secondaryHref}>
                  {SecondaryIcon ? <SecondaryIcon className="size-4" /> : null}
                  {secondaryLabel}
                </Link>
              </Button>
            ) : null}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="px-6 py-6 text-center text-sm text-muted-foreground">
        © {new Date().getFullYear()} OrbynAdmin. All rights reserved.
      </footer>
    </div>
  );
}
