import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A single keyboard keycap. Compose several side by side to show a shortcut,
 * e.g. `<Kbd>⌘</Kbd><Kbd>K</Kbd>`. `min-w-5` keeps single characters square
 * while longer labels (Ctrl, Esc, Enter) grow to fit.
 */
function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "pointer-events-none inline-flex h-5 min-w-5 select-none items-center justify-center gap-1 rounded-[5px] border bg-muted px-1 text-center font-sans text-[11px] font-medium text-muted-foreground",
        className
      )}
      {...props}
    />
  );
}

/** A row of keycaps with consistent spacing. */
function KbdGroup({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="kbd-group"
      className={cn("inline-flex items-center gap-1", className)}
      {...props}
    />
  );
}

export { Kbd, KbdGroup };
