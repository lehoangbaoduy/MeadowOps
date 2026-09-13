import {
  IconLayoutDashboard,
  IconChartBar,
  IconReportAnalytics,
  IconShoppingCart,
  IconUsers,
  IconPackages,
  IconTruck,
  IconActivity,
  IconBell,
  IconSettings,
  IconAlertTriangle,
  IconSparkles,
  IconBuildingWarehouse,
  IconTerminal2,
  IconMessageCircle,
  IconHistory,
  type Icon,
} from "@tabler/icons-react";

export type Workspace = {
  name: string;
  plan: string;
  icon: Icon;
};

export const workspaces: Workspace[] = [
  { name: "MeadowOps", plan: "Control Tower", icon: IconSparkles },
];

export type NavChild = { title: string; url: string };

export type NavItem = {
  title: string;
  url?: string;
  icon?: Icon;
  badge?: string;
  items?: NavChild[];
  /**
   * Unit 28 (MEADOWOPS-API-005, PRD 6.12): hides the item from the Analyst
   * role. Cosmetic only — the actual boundary is the backend's
   * require_admin on the route this links to (app.core.auth); AppSidebar
   * filters on this flag using the role passed down from AppLayout's
   * server-side getCurrentRole().
   */
  adminOnly?: boolean;
};

export type NavGroup = {
  label: string;
  items: NavItem[];
};

export const navGroups: NavGroup[] = [
  {
    label: "Dashboards",
    items: [
      { title: "Overview", url: "/dashboard", icon: IconLayoutDashboard },
      { title: "Analytics", url: "/dashboard/analytics", icon: IconChartBar },
      { title: "Reports", url: "/reports", icon: IconReportAnalytics },
    ],
  },
  {
    label: "Operations",
    items: [
      {
        title: "Orders",
        icon: IconShoppingCart,
        items: [
          { title: "Purchase Orders", url: "/orders" },
          { title: "Sales Orders", url: "/orders/sales" },
        ],
      },
      {
        title: "Customers",
        icon: IconUsers,
        items: [
          { title: "All Customers", url: "/customers" },
          { title: "Add Customer", url: "/customers/new" },
        ],
      },
      { title: "Inventory", url: "/inventory", icon: IconPackages },
      { title: "Suppliers", url: "/suppliers", icon: IconBuildingWarehouse },
      { title: "Shipping", url: "/shipping", icon: IconTruck },
      { title: "Activity", url: "/activity", icon: IconActivity },
      { title: "Query", url: "/query", icon: IconTerminal2 },
      {
        title: "Query Log",
        url: "/admin/query-log",
        icon: IconHistory,
        adminOnly: true,
      },
      { title: "Chat", url: "/chat", icon: IconMessageCircle },
    ],
  },
  {
    label: "Account",
    items: [
      { title: "Settings", url: "/settings", icon: IconSettings },
      { title: "Notifications", url: "/notifications", icon: IconBell },
    ],
  },
  {
    label: "Pages",
    items: [
      {
        title: "Error Pages",
        icon: IconAlertTriangle,
        items: [{ title: "404 · Not Found", url: "/errors/404" }],
      },
    ],
  },
];
