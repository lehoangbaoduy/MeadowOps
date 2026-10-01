"use client";

import * as React from "react";
import {
  IconAlertTriangle,
  IconKey,
  IconPlus,
  IconSitemap,
  IconZoomIn,
  IconZoomOut,
} from "@tabler/icons-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

// Unit 36 (MEADOWOPS-DOM-024): mirrors GET /api/v1/query/schema - the tables
// the Analyst can actually query (the sandbox schema), so she isn't left
// guessing names and guessing into `live.*`, which her role is denied.
interface SchemaColumn {
  name: string;
  type: string;
  nullable: boolean;
  is_primary_key: boolean;
}
interface SchemaTable {
  name: string;
  qualified_name: string;
  columns: SchemaColumn[];
}
interface SchemaRelationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
}
interface SandboxSchema {
  tables: SchemaTable[];
  relationships: SchemaRelationship[];
  sandbox_populated: boolean | null;
}

const SAFE_IDENTIFIER = /[^A-Za-z0-9_]/g;

/**
 * Mermaid ER definition. Identifiers are reduced to [A-Za-z0-9_] so nothing
 * from the schema payload can inject diagram syntax. Only key columns (PK +
 * FK) are drawn: all columns of 24 tables is unreadable, and the full column
 * list is one click away in the side panel.
 */
export function buildErDiagram(schema: SandboxSchema): string {
  const clean = (value: string) => value.replace(SAFE_IDENTIFIER, "_");
  const foreignKeyColumns = new Map<string, Set<string>>();
  for (const rel of schema.relationships) {
    const set = foreignKeyColumns.get(rel.from_table) ?? new Set<string>();
    set.add(rel.from_column);
    foreignKeyColumns.set(rel.from_table, set);
  }

  const lines = ["erDiagram"];
  for (const rel of schema.relationships) {
    lines.push(
      `  ${clean(rel.from_table)} }o--|| ${clean(rel.to_table)} : "${clean(rel.from_column)}"`,
    );
  }
  for (const table of schema.tables) {
    const fks = foreignKeyColumns.get(table.name) ?? new Set<string>();
    const keyColumns = table.columns.filter((c) => c.is_primary_key || fks.has(c.name));
    lines.push(`  ${clean(table.name)} {`);
    for (const column of keyColumns) {
      const keys = [column.is_primary_key ? "PK" : null, fks.has(column.name) ? "FK" : null]
        .filter(Boolean)
        .join(",");
      const type = clean(column.type.split("(")[0].trim()) || "unknown";
      lines.push(`    ${type} ${clean(column.name)} ${keys}`.trimEnd());
    }
    lines.push("  }");
  }
  return lines.join("\n");
}

const DIAGRAM_ZOOM_STEPS = [0.3, 0.4, 0.5, 0.65, 0.8, 1];
const DIAGRAM_DEFAULT_ZOOM_INDEX = 2;

function ErDiagram({ schema }: { schema: SandboxSchema }) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [error, setError] = React.useState<string | null>(null);
  const renderId = React.useId().replace(/[^A-Za-z0-9_]/g, "");
  const [naturalWidth, setNaturalWidth] = React.useState<number | null>(null);
  const [zoomIndex, setZoomIndex] = React.useState(DIAGRAM_DEFAULT_ZOOM_INDEX);

  React.useEffect(() => {
    let cancelled = false;
    async function render() {
      try {
        setError(null);
        const { default: mermaid } = await import("mermaid");
        const dark = document.documentElement.classList.contains("dark");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: dark ? "dark" : "default",
          er: { useMaxWidth: false },
        });
        const { svg } = await mermaid.render(`er${renderId}`, buildErDiagram(schema));
        // Safe: mermaid runs in strict mode and every identifier in the
        // definition was reduced to [A-Za-z0-9_] by buildErDiagram.
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        const drawn = containerRef.current.querySelector("svg");
        setNaturalWidth(drawn?.viewBox.baseVal.width || null);
      } catch {
        if (!cancelled) setError("Couldn't draw the diagram. The table list still shows every column.");
      }
    }
    void render();
    return () => {
      cancelled = true;
    };
  }, [schema, renderId]);

  React.useEffect(() => {
    const drawn = containerRef.current?.querySelector("svg");
    if (!drawn || !naturalWidth) return;
    drawn.style.maxWidth = "none";
    drawn.style.height = "auto";
    drawn.style.width = `${naturalWidth * DIAGRAM_ZOOM_STEPS[zoomIndex]}px`;
  }, [naturalWidth, zoomIndex]);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Button
          variant="outline"
          size="icon"
          className="size-7"
          onClick={() => setZoomIndex((i) => Math.max(0, i - 1))}
          disabled={zoomIndex === 0}
          aria-label="Zoom out"
        >
          <IconZoomOut className="size-4" />
        </Button>
        <span className="w-10 text-center">{Math.round(DIAGRAM_ZOOM_STEPS[zoomIndex] * 100)}%</span>
        <Button
          variant="outline"
          size="icon"
          className="size-7"
          onClick={() => setZoomIndex((i) => Math.min(DIAGRAM_ZOOM_STEPS.length - 1, i + 1))}
          disabled={zoomIndex === DIAGRAM_ZOOM_STEPS.length - 1}
          aria-label="Zoom in"
        >
          <IconZoomIn className="size-4" />
        </Button>
      </div>
      <div ref={containerRef} className="overflow-auto" aria-label="Entity relationship diagram" />
    </div>
  );
}

interface SchemaBrowserProps {
  /** Appends text to the SQL editor. */
  onInsert: (text: string) => void;
  /** Changes after each sandbox refresh so the panel reloads. */
  reloadKey: number;
}

export function SchemaBrowser({ onInsert, reloadKey }: SchemaBrowserProps) {
  const [schema, setSchema] = React.useState<SandboxSchema | null>(null);
  const [loadError, setLoadError] = React.useState(false);
  const [filter, setFilter] = React.useState("");
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [diagramOpen, setDiagramOpen] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/api/query/schema", { cache: "no-store" });
        if (!response.ok) throw new Error(String(response.status));
        const body = (await response.json()) as SandboxSchema;
        if (!cancelled) {
          setSchema(body);
          setLoadError(false);
        }
      } catch {
        if (!cancelled) setLoadError(true);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  function toggle(name: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const visibleTables = (schema?.tables ?? []).filter((table) => {
    const needle = filter.trim().toLowerCase();
    return (
      needle === "" ||
      table.name.includes(needle) ||
      table.columns.some((column) => column.name.includes(needle))
    );
  });

  return (
    <aside className="space-y-3 rounded-lg border p-3" aria-label="Database schema">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Tables you can query</h2>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDiagramOpen(true)}
          disabled={!schema || schema.tables.length === 0}
        >
          <IconSitemap className="size-4" />
          Diagram
        </Button>
      </div>

      {loadError && (
        <Alert variant="destructive">
          <IconAlertTriangle className="size-4" />
          <AlertTitle>Couldn&apos;t load the schema</AlertTitle>
          <AlertDescription>Reload the page to try again.</AlertDescription>
        </Alert>
      )}

      {schema && schema.sandbox_populated === false && (
        <Alert>
          <IconAlertTriangle className="size-4" />
          <AlertTitle>The sandbox is empty</AlertTitle>
          <AlertDescription>
            Click &ldquo;Refresh sandbox&rdquo; to load a copy of the data. Until then these
            tables don&apos;t exist for your queries.
          </AlertDescription>
        </Alert>
      )}

      {schema && (
        <>
          <p className="text-xs text-muted-foreground">
            Query these as <code className="font-mono">sandbox.table_name</code>. Other schemas
            (<code className="font-mono">live</code>, <code className="font-mono">reporting</code>)
            are off-limits and will return &ldquo;permission denied&rdquo;.
          </p>
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter tables or columns…"
            aria-label="Filter tables or columns"
          />
          <ul className="max-h-[420px] space-y-1 overflow-auto">
            {visibleTables.map((table) => {
              const isOpen = expanded.has(table.name) || filter.trim() !== "";
              return (
                <li key={table.name} className="rounded-md border">
                  <div className="flex items-center gap-1 p-1">
                    <button
                      type="button"
                      onClick={() => toggle(table.name)}
                      aria-expanded={isOpen}
                      className="flex-1 truncate rounded px-2 py-1 text-left font-mono text-xs hover:bg-muted"
                    >
                      {table.name}
                      <span className="ml-2 text-muted-foreground">{table.columns.length}</span>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      onClick={() => onInsert(table.qualified_name)}
                      aria-label={`Insert ${table.qualified_name} into the editor`}
                    >
                      <IconPlus className="size-4" />
                    </Button>
                  </div>
                  {isOpen && (
                    <ul className="space-y-0.5 border-t px-2 py-1">
                      {table.columns.map((column) => (
                        <li key={column.name} className="flex items-center gap-2 text-xs">
                          <button
                            type="button"
                            className="font-mono hover:underline"
                            onClick={() => onInsert(column.name)}
                            aria-label={`Insert column ${column.name} into the editor`}
                          >
                            {column.name}
                          </button>
                          {column.is_primary_key && (
                            <IconKey className="size-3 text-muted-foreground" aria-label="primary key" />
                          )}
                          <span className="ml-auto text-muted-foreground">{column.type.toLowerCase()}</span>
                          {column.nullable && <Badge variant="secondary">null</Badge>}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
            {visibleTables.length === 0 && (
              <li className="p-2 text-xs text-muted-foreground">No tables match &ldquo;{filter}&rdquo;.</li>
            )}
          </ul>
        </>
      )}

      {!schema && !loadError && <p className="text-xs text-muted-foreground">Loading schema…</p>}

      <Dialog open={diagramOpen} onOpenChange={setDiagramOpen}>
        <DialogContent className="max-h-[90vh] w-[95vw] max-w-none overflow-auto sm:max-w-[90vw]">
          <DialogHeader>
            <DialogTitle>How the tables relate</DialogTitle>
            <DialogDescription>
              Each arrow points from a table to the table its column refers to. Only key columns
              are drawn; expand a table in the side panel for the rest.
            </DialogDescription>
          </DialogHeader>
          {schema && diagramOpen && <ErDiagram schema={schema} />}
        </DialogContent>
      </Dialog>
    </aside>
  );
}
