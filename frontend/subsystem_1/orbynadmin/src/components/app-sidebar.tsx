"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconChevronRight } from "@tabler/icons-react";

import { cn } from "@/lib/utils";
import { navGroups, type NavItem } from "@/config/nav";
import { TeamSwitcher } from "@/components/team-switcher";
import { NavUser } from "@/components/nav-user";
import { useThemeConfig } from "@/components/theme-customizer";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";

export function AppSidebar({ role }: { role?: string | null }) {
  const pathname = usePathname();
  const { config } = useThemeConfig();

  // Unit 28 (MEADOWOPS-API-005): drops adminOnly items for a non-admin role
  // (and the Analyst's not-yet-known-during-SSR-fallback null) — cosmetic
  // only, see NavItem.adminOnly's own comment for the real boundary.
  const visibleGroups = navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.adminOnly || role === "admin"),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <Sidebar
      collapsible={config.sidebarCollapsible}
      variant={config.sidebarVariant}
    >
      <SidebarHeader>
        <TeamSwitcher />
      </SidebarHeader>

      <SidebarContent className="overscroll-contain">
        {visibleGroups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarMenu>
              {group.items.map((item) => (
                <NavEntry key={item.title} item={item} pathname={pathname} />
              ))}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

function badgeClass(badge: string) {
  return /^\d+$/.test(badge)
    ? "bg-sidebar-accent text-sidebar-accent-foreground"
    : "bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground peer-hover/menu-button:text-primary-foreground peer-data-active/menu-button:text-primary-foreground";
}

function NavEntry({ item, pathname }: { item: NavItem; pathname: string }) {
  const { setOpenMobile } = useSidebar();
  const closeMobile = () => setOpenMobile(false);

  // Collapsible parent with children.
  if (item.items?.length) {
    const childActive = item.items.some((c) => pathname === c.url);
    return (
      <Collapsible
        asChild
        defaultOpen={childActive}
        className="group/collapsible"
      >
        <SidebarMenuItem>
          <CollapsibleTrigger asChild>
            <SidebarMenuButton tooltip={item.title} isActive={childActive}>
              {item.icon && <item.icon className="size-4" />}
              <span>{item.title}</span>
              {item.badge && (
                <SidebarMenuBadge
                  className={cn(
                    "group-data-[state=open]/collapsible:hidden",
                    badgeClass(item.badge)
                  )}
                >
                  {item.badge}
                </SidebarMenuBadge>
              )}
              <IconChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
            </SidebarMenuButton>
          </CollapsibleTrigger>
          <CollapsibleContent className="overflow-hidden [--tw-animation-duration:260ms] data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
            <SidebarMenuSub>
              {item.items.map((sub) => (
                <SidebarMenuSubItem key={sub.title}>
                  <SidebarMenuSubButton asChild isActive={pathname === sub.url}>
                    <Link href={sub.url} onClick={closeMobile}>
                      {sub.title}
                    </Link>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
              ))}
            </SidebarMenuSub>
          </CollapsibleContent>
        </SidebarMenuItem>
      </Collapsible>
    );
  }

  // Flat link item.
  const active =
    pathname === item.url ||
    (item.url !== "/dashboard" && !!item.url && pathname.startsWith(item.url));
  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild isActive={active} tooltip={item.title}>
        <Link href={item.url ?? "#"} onClick={closeMobile}>
          {item.icon && <item.icon className="size-4" />}
          <span>{item.title}</span>
        </Link>
      </SidebarMenuButton>
      {item.badge && (
        <SidebarMenuBadge className={badgeClass(item.badge)}>
          {item.badge}
        </SidebarMenuBadge>
      )}
    </SidebarMenuItem>
  );
}
