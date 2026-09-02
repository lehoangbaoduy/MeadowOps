# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pnpm dev      # start dev server (Turbopack, default port 3000)
pnpm build    # production build
pnpm start    # run production build
pnpm lint     # eslint (eslint-config-next)
```

There is no test suite configured in this repo (repo-root `tests/frontend/` covers structural facts about this template's file layout, not its runtime behavior).

Package manager is pnpm (`pnpm-lock.yaml` is present) — don't use npm/yarn commands that would create a competing lockfile.

## Architecture

This is a shadcn/ui admin dashboard template built on Next.js 16 (App Router) + React 19 + Tailwind v4, adapted as the frontend for MeadowOps Subsystem 2 (the Analyst Work Simulation Engine — see `prd/MeadowOps_PRD_FINAL.md` Appendix D.2). It ships with no real backend wiring yet (that starts at Unit 8+) — pages render an "empty state" rather than mock data. `src/middleware.ts` handles one legacy redirect (`/login` → `/sign-in`).

Unit 7 (MEADOWOPS-INFRA-002) stripped this template down to only the pages Appendix D.2 selects — the original upstream template shipped a much larger page set (landing page, chat, pricing, FAQs, multiple auth-page style variants, several dashboard variants, a "production"/JW Fresh dashboard) which has been deleted entirely, not just hidden. Don't recreate those routes without checking Appendix D.2 first.

### Route groups

- `src/app/(dashboard)/` — authenticated-app pages: `dashboard` (Home — Open Work/Company Status/Notifications/Completed Work, PRD 6.1), `mail` (the core work interface — Inbox/Read/Compose), `calendar` (response-window deadlines), `tasks` (optional kanban view), `users` (repurposed as the table pattern for scenario/portfolio history and the SQL query-history admin view, PRD 6.12 — not literal user management), `settings/{account,appearance,notifications,user}`. Shares `(dashboard)/layout.tsx`.
- `src/app/(auth)/` — `sign-in` (single variant — PRD 8.4 specifies simple bearer-token auth, not the original template's OAuth/multi-variant sign-up/sign-in flows) and `errors/not-found`. Shares `(auth)/layout.tsx`.

Each feature route follows the same local structure: `page.tsx` + a `components/` subfolder for page-specific components, and sometimes `data.ts`/`schemas/` for type definitions (kept mostly as empty arrays post-Unit-7, not mock data — see `mail/data.tsx`). Keep new page-specific components colocated the same way rather than pushing them into `src/components`.

### Dashboard shell composition

`(dashboard)/layout.tsx` wires together `AppSidebar`, `SiteHeader`, `SiteFooter`, `SidebarProvider`/`SidebarInset` (from `components/ui/sidebar.tsx`, the shadcn sidebar primitive), plus the floating `ThemeCustomizer` sheet. Sidebar `variant`/`collapsible`/`side` are runtime-configurable (not just CSS) via `SidebarConfigProvider` (`src/contexts/sidebar-context.tsx`, exposed through `useSidebarConfig`) — the layout branches its JSX structure (sidebar-before-vs-after-content) based on `config.side`. The theme customizer's "Layout" tab writes into this same context, so sidebar placement/behavior is live-editable from the UI at `src/components/theme-customizer/layout-tab.tsx`.

Nav content for the sidebar is a single static data object in `src/components/app-sidebar.tsx` (`navGroups` → groups → items, optionally with nested `items` for flyout submenus like Errors/Settings). Add new sidebar entries there — keep them scoped to what Appendix D.2 actually selects.

### Theming system

Theming is CSS-variable driven (Tailwind v4, no `tailwind.config` — see `components.json`: `cssVariables: true`, css entry `src/app/globals.css`) and has three independent layers, all orchestrated by `useThemeManager` (`src/hooks/use-theme-manager.ts`):

- Light/dark mode via `next-themes` (`ThemeProvider` in `src/components/theme-provider.tsx`, root-level in `app/layout.tsx`).
- Color theme presets: shadcn presets (`src/utils/shadcn-ui-theme-presets.ts`) and tweakcn presets (`src/utils/tweakcn-theme-presets.ts`), both normalized into `ColorTheme[]` in `src/config/theme-data.ts`.
- Radius and custom "imported" themes (raw CSS variables pasted by the user), typed in `src/types/theme-customizer.ts`.

The `ThemeCustomizer` (`src/components/theme-customizer/index.tsx`) is the single UI surface for all of this (`ThemeTab` for colors/radius, `LayoutTab` for sidebar config, `ImportModal` for pasting custom themes) and is lazy-loaded via `src/components/dynamic-imports.ts` (`ssr: false`) since it's non-critical UI. Follow that dynamic-import pattern for other heavy, below-the-fold, or client-only widgets.

### Dashboard page pattern

`dashboard/page.tsx` (the Home page, PRD 6.1) is currently a thin empty-state stub post-Unit-7 — real content (Open Work list, Company Status, Notifications, Completed Work) is deferred to a later unit. When building it out, follow the `@container/main` + responsive grid convention already used across the template's surviving pages rather than reintroducing the deleted `dashboard-2` variant's component split. Charts use `recharts` wrapped by shadcn's `ChartContainer`/`ChartConfig` in `src/components/ui/chart.tsx` — use that wrapper rather than raw recharts components so colors track the active theme. Note: `chart.tsx`'s `ChartTooltipContent`/`ChartLegendContent` prop types are hand-typed (not `React.ComponentProps<typeof RechartsPrimitive.*>`) because recharts 3.x's public types no longer expose several fields (`payload`, `label`, `verticalAlign`, etc.) that are still passed at runtime — don't "simplify" this back to the recharts-derived type without checking `next build`'s TypeScript check still passes.

### Path aliases

`@/*` → `src/*` (see `tsconfig.json` and `components.json` aliases: `@/components`, `@/components/ui`, `@/lib`, `@/hooks`). shadcn/ui components live in `src/components/ui/`; add new shadcn primitives there via the shadcn CLI rather than hand-rolling equivalents.
