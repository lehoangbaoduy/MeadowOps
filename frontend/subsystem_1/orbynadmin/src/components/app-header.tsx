"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  IconBell,
  IconSearch,
  IconLogout,
  IconSettings,
  IconBellOff,
} from "@tabler/icons-react";

import { navGroups } from "@/config/nav";
import { useIsMac } from "@/hooks/use-platform";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { CustomizerButton } from "@/components/theme-customizer";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

// Acronyms that shouldn't be title-cased from the URL segment.
const CRUMB_LABELS: Record<string, string> = {
  api: "API",
};

function useBreadcrumb() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);
  return segments.map(
    (s) =>
      CRUMB_LABELS[s] ??
      s.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export function AppHeader() {
  const crumbs = useBreadcrumb();
  const router = useRouter();
  const isMac = useIsMac();
  const [open, setOpen] = React.useState(false);

  const go = React.useCallback(
    (url: string) => {
      setOpen(false);
      router.push(url);
    },
    [router]
  );

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <SidebarTrigger className="-ml-1" />
      <div className="mr-1 h-5 w-px shrink-0 self-center bg-border" />
      <Breadcrumb className="hidden sm:block">
        <BreadcrumbList>
          {crumbs.map((c, i) => (
            <React.Fragment key={i}>
              <BreadcrumbItem>
                <BreadcrumbPage
                  className={
                    i < crumbs.length - 1 ? "text-muted-foreground" : ""
                  }
                >
                  {c}
                </BreadcrumbPage>
              </BreadcrumbItem>
              {i < crumbs.length - 1 && <BreadcrumbSeparator />}
            </React.Fragment>
          ))}
        </BreadcrumbList>
      </Breadcrumb>

      <div className="ml-auto flex items-center gap-1.5">
        <Button
          variant="outline"
          className="hidden h-9 w-56 justify-start gap-2 px-3 text-muted-foreground md:flex"
          onClick={() => setOpen(true)}
        >
          <IconSearch className="size-4" />
          <span className="text-sm">Search…</span>
          <KbdGroup className="ml-auto">
            <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
            <span className="text-[11px] font-medium text-muted-foreground">+</span>
            <Kbd>K</Kbd>
          </KbdGroup>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="rounded-full md:hidden"
          onClick={() => setOpen(true)}
        >
          <IconSearch className="size-5" />
        </Button>

        <NotificationsMenu />
        <ThemeToggle />
        <CustomizerButton />
        <div className="mx-1 h-6 w-px shrink-0 self-center bg-border" />
        <UserMenu />
      </div>

      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Type a command or search…" />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          {navGroups.map((group) => (
            <CommandGroup key={group.label} heading={group.label}>
              {group.items.flatMap((item) => {
                if (item.items?.length) {
                  return item.items.map((sub) => (
                    <CommandItem
                      key={sub.title}
                      value={`${item.title} ${sub.title}`}
                      onSelect={() => go(sub.url)}
                    >
                      {item.icon && <item.icon className="size-4" />}
                      <span className="min-w-0 flex-1 truncate">{sub.title}</span>
                    </CommandItem>
                  ));
                }
                return (
                  <CommandItem
                    key={item.title}
                    value={item.title}
                    onSelect={() => go(item.url ?? "#")}
                  >
                    {item.icon && <item.icon className="size-4" />}
                    <span className="min-w-0 flex-1 truncate">{item.title}</span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          ))}
        </CommandList>
      </CommandDialog>
    </header>
  );
}

function NotificationsMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative rounded-full"
          aria-label="Notifications"
        >
          <IconBell className="size-5" />
          <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-destructive ring-2 ring-background" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[calc(100vw-1rem)] sm:w-80">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="flex flex-col items-center gap-1.5 px-4 py-6 text-center">
          <IconBellOff className="size-5 text-muted-foreground opacity-50" />
          <p className="text-sm text-muted-foreground">No notifications yet</p>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild className="justify-center text-sm font-medium">
          <Link href="/notifications">View all notifications</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-9 gap-2 px-1.5">
          <Avatar className="size-7">
            <AvatarFallback>B</AvatarFallback>
          </Avatar>
          <span className="hidden text-sm font-medium lg:inline">Builder</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="flex items-center gap-2">
          <Avatar className="size-8 shrink-0">
            <AvatarFallback>B</AvatarFallback>
          </Avatar>
          <div className="grid min-w-0">
            <span className="truncate text-sm font-medium">Builder</span>
            <span className="truncate text-xs text-muted-foreground">
              Shared bearer-token access (PRD 8.4)
            </span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem asChild>
            <Link href="/settings">
              <IconSettings className="size-4" /> Settings
            </Link>
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/login">
            <IconLogout className="size-4" /> Log out
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
