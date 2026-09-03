"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/settings/products", label: "Products" },
  { href: "/settings/warehouses", label: "Warehouses" },
  { href: "/settings/suppliers", label: "Suppliers" },
  { href: "/settings/carriers", label: "Carriers" },
];

export default function SettingsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Master-data CRUD (PRD 5.6 / S1-FR-12) — create, edit, and deactivate the starting Product/Warehouse/Supplier/Carrier catalog."
      />
      <div className="flex gap-1 border-b">
        {TABS.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "border-b-2 px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
              pathname === tab.href
                ? "border-primary text-foreground"
                : "border-transparent"
            )}
          >
            {tab.label}
          </Link>
        ))}
      </div>
      {children}
    </div>
  );
}
