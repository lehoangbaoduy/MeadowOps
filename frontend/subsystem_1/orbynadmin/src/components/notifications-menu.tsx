"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { IconBell, IconBellOff, IconClock, IconMessage } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  notificationTitle,
  unreadCount,
  type NotificationFeedItem,
} from "@/lib/notification-feed";

const REFRESH_MS = 30_000;
const MENU_ITEM_LIMIT = 5;

// Unit 39 (MEADOWOPS-DOM-027): the badge used to be a hardcoded dot over a
// hardcoded "No notifications yet". It now reflects the real feed - deadline
// notifications plus replies the user has not read - and is simply absent
// when there is nothing to be told.
export function NotificationsMenu() {
  const pathname = usePathname();
  const [items, setItems] = React.useState<NotificationFeedItem[]>([]);

  const refresh = React.useCallback(async () => {
    try {
      const response = await fetch("/api/notifications/feed", { cache: "no-store" });
      if (!response.ok) return;
      const body: unknown = await response.json();
      if (Array.isArray(body)) setItems(body as NotificationFeedItem[]);
    } catch {
      // Keep whatever was last shown; the next poll retries.
    }
  }, []);

  React.useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), REFRESH_MS);
    window.addEventListener("focus", refresh);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", refresh);
    };
  }, [refresh, pathname]);

  const unread = unreadCount(items);
  const shown = items.slice(0, MENU_ITEM_LIMIT);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative rounded-full"
          aria-label={unread > 0 ? `Notifications (${unread} unread)` : "Notifications"}
        >
          <IconBell className="size-5" />
          {unread > 0 && (
            <span
              data-testid="notification-badge"
              className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-none text-white ring-2 ring-background"
            >
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[calc(100vw-1rem)] sm:w-80">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {shown.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 px-4 py-6 text-center">
            <IconBellOff className="size-5 text-muted-foreground opacity-50" />
            <p className="text-sm text-muted-foreground">You&apos;re all caught up</p>
          </div>
        ) : (
          shown.map((item) => (
            <DropdownMenuItem key={item.id} asChild className="items-start gap-2 py-2">
              <Link href="/chat">
                {item.kind === "new_reply" ? (
                  <IconMessage className="mt-0.5 size-4 shrink-0" />
                ) : (
                  <IconClock className="mt-0.5 size-4 shrink-0" />
                )}
                <span className="grid min-w-0 gap-0.5">
                  <span className={item.is_read ? "text-sm" : "text-sm font-medium"}>
                    {notificationTitle(item)}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {item.scenario_title} ·{" "}
                    {formatDistanceToNow(new Date(item.occurred_at), { addSuffix: true })}
                  </span>
                </span>
              </Link>
            </DropdownMenuItem>
          ))
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild className="justify-center text-sm font-medium">
          <Link href="/notifications">View all notifications</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
