"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import {
  IconCopy,
  IconMoon,
  IconSun,
  IconDeviceDesktop,
  IconPalette,
} from "@tabler/icons-react";

import {
  type ThemeConfig,
  defaultConfig,
  accents,
  radii,
  fonts,
  sidebarVariants,
  collapsibleModes,
  contentLayouts,
  buildThemeCss,
} from "@/lib/theme-config";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

type Ctx = {
  config: ThemeConfig;
  setConfig: React.Dispatch<React.SetStateAction<ThemeConfig>>;
  reset: () => void;
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
};

const ThemeConfigContext = React.createContext<Ctx | null>(null);

export function useThemeConfig() {
  const ctx = React.useContext(ThemeConfigContext);
  if (!ctx) {
    // Safe fallback so components work outside the provider (e.g. tests).
    return {
      config: defaultConfig,
      setConfig: () => {},
      reset: () => {},
      open: false,
      setOpen: () => {},
    } as Ctx;
  }
  return ctx;
}

const STORAGE_KEY = "orbynadmin-theme-config";

export function ThemeConfigProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [config, setConfig] = React.useState<ThemeConfig>(defaultConfig);
  const [open, setOpen] = React.useState(false);

  // Load persisted config once on mount.
  React.useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setConfig({ ...defaultConfig, ...JSON.parse(raw) });
    } catch {
      // ignore
    }
  }, []);

  // Apply config to the document + persist.
  React.useEffect(() => {
    const root = document.documentElement;
    const accent = accents.find((a) => a.key === config.accent);
    const props = [
      "--primary",
      "--primary-foreground",
      "--ring",
      "--sidebar-primary",
      "--sidebar-ring",
    ];
    if (accent?.primary) {
      root.style.setProperty("--primary", accent.primary);
      root.style.setProperty("--primary-foreground", accent.fg);
      root.style.setProperty("--ring", accent.primary);
      root.style.setProperty("--sidebar-primary", accent.primary);
      root.style.setProperty("--sidebar-ring", accent.primary);
    } else {
      props.forEach((p) => root.style.removeProperty(p));
    }

    root.style.setProperty("--radius", `${config.radius}rem`);

    const font = fonts.find((f) => f.key === config.font);
    if (font?.stack) root.style.setProperty("--font-sans", font.stack);
    else root.style.removeProperty("--font-sans");

    root.dataset.content = config.contentLayout;

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    } catch {
      // ignore
    }
  }, [config]);

  const reset = React.useCallback(() => setConfig(defaultConfig), []);

  return (
    <ThemeConfigContext.Provider
      value={{ config, setConfig, reset, open, setOpen }}
    >
      {children}
    </ThemeConfigContext.Provider>
  );
}

/** Colorful color-wheel button for the header, next to the theme toggle. */
export function CustomizerButton() {
  const { setOpen } = useThemeConfig();
  return (
    <Button
      variant="ghost"
      size="icon"
      className="rounded-full"
      aria-label="Customize theme"
      onClick={() => setOpen(true)}
    >
      <IconPalette className="size-5" />
    </Button>
  );
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2.5">
      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        {label}
      </Label>
      {children}
    </div>
  );
}

function OptionButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex h-9 items-center justify-center gap-1.5 rounded-md border px-2 text-xs font-medium transition-colors",
        active
          ? "border-primary bg-primary/10 text-foreground"
          : "border-border text-muted-foreground hover:bg-accent"
      )}
    >
      {children}
    </button>
  );
}

export function ThemeCustomizer() {
  const { config, setConfig, reset, open, setOpen } = useThemeConfig();
  const { theme, setTheme } = useTheme();

  function copyConfig() {
    const css = buildThemeCss(config);
    navigator.clipboard.writeText(css).then(
      () => toast.success("Theme copied", { description: "Paste it into your globals.css" }),
      () => toast.error("Could not copy to clipboard")
    );
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-sm">
        <SheetHeader className="shrink-0 border-b">
          <SheetTitle>Customize</SheetTitle>
          <SheetDescription>
            Tune the theme and copy the config into your project.
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="space-y-6 p-4">
            <Section label="Mode">
              <div className="grid grid-cols-3 gap-2">
                <OptionButton active={theme === "light"} onClick={() => setTheme("light")}>
                  <IconSun className="size-4" /> Light
                </OptionButton>
                <OptionButton active={theme === "dark"} onClick={() => setTheme("dark")}>
                  <IconMoon className="size-4" /> Dark
                </OptionButton>
                <OptionButton active={theme === "system"} onClick={() => setTheme("system")}>
                  <IconDeviceDesktop className="size-4" /> Auto
                </OptionButton>
              </div>
            </Section>

            <Section label="Accent color">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-2">
                {accents.map((a) => (
                  <button
                    key={a.key}
                    type="button"
                    onClick={() => setConfig((c) => ({ ...c, accent: a.key }))}
                    className={cn(
                      "flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                      config.accent === a.key
                        ? "border-primary"
                        : "border-border hover:bg-accent"
                    )}
                  >
                    <span
                      className="size-4 shrink-0 rounded-full"
                      style={{ background: a.swatch }}
                    />
                    <span className="truncate">{a.label}</span>
                  </button>
                ))}
              </div>
            </Section>

            <Section label="Radius">
              <div className="grid grid-cols-6 gap-2">
                {radii.map((r) => (
                  <OptionButton
                    key={r.value}
                    active={config.radius === r.value}
                    onClick={() => setConfig((c) => ({ ...c, radius: r.value }))}
                  >
                    {r.label}
                  </OptionButton>
                ))}
              </div>
            </Section>

            <Section label="Font">
              <div className="grid grid-cols-2 gap-2">
                {fonts.map((f) => (
                  <OptionButton
                    key={f.key}
                    active={config.font === f.key}
                    onClick={() => setConfig((c) => ({ ...c, font: f.key }))}
                  >
                    {f.label}
                  </OptionButton>
                ))}
              </div>
            </Section>

            <Separator />

            <Section label="Sidebar style">
              <div className="grid grid-cols-3 gap-2">
                {sidebarVariants.map((v) => (
                  <OptionButton
                    key={v.key}
                    active={config.sidebarVariant === v.key}
                    onClick={() =>
                      setConfig((c) => ({ ...c, sidebarVariant: v.key }))
                    }
                  >
                    {v.label}
                  </OptionButton>
                ))}
              </div>
            </Section>

            <Section label="Sidebar collapse">
              <div className="grid grid-cols-2 gap-2">
                {collapsibleModes.map((m) => (
                  <OptionButton
                    key={m.key}
                    active={config.sidebarCollapsible === m.key}
                    onClick={() =>
                      setConfig((c) => ({ ...c, sidebarCollapsible: m.key }))
                    }
                  >
                    {m.label}
                  </OptionButton>
                ))}
              </div>
            </Section>

            <Section label="Content layout">
              <div className="grid grid-cols-2 gap-2">
                {contentLayouts.map((l) => (
                  <OptionButton
                    key={l.key}
                    active={config.contentLayout === l.key}
                    onClick={() =>
                      setConfig((c) => ({ ...c, contentLayout: l.key }))
                    }
                  >
                    {l.label}
                  </OptionButton>
                ))}
              </div>
            </Section>
          </div>
        </div>

        <div className="flex shrink-0 gap-2 border-t p-4">
          <Button variant="outline" className="flex-1" onClick={reset}>
            Reset
          </Button>
          <Button className="flex-1" onClick={copyConfig}>
            <IconCopy className="size-4" /> Copy config
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
