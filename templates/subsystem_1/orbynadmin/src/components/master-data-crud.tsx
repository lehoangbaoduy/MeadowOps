"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { type ColumnDef } from "@tanstack/react-table";
import { IconPencil, IconPlus } from "@tabler/icons-react";
import { toast } from "sonner";

import { DataTable, SortableHeader } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

export type FieldType = "text" | "integer" | "decimal" | "select" | "switch";

export interface FieldOption {
  value: string;
  label: string;
}

export interface FieldConfig {
  name: string;
  label: string;
  type: FieldType;
  options?: FieldOption[];
  /** false = business natural key, set once at create, never in a PATCH
   * (mirrors the backend's *Update schemas, which omit `id` entirely —
   * app/schemas/master_data.py). */
  editable?: boolean;
  min?: number;
  max?: number;
  step?: string;
}

export interface MasterDataRow {
  id: string;
  is_active: boolean;
  [key: string]: unknown;
}

interface MasterDataCrudProps {
  /** URL/API path segment, e.g. "warehouses" — matches
   * backend/app/api/master_data.py's route prefixes one-to-one. */
  entity: string;
  entityLabel: string;
  fields: FieldConfig[];
  initialData: MasterDataRow[];
}

type FormValues = Record<string, string | boolean>;

function emptyFormValues(fields: FieldConfig[]): FormValues {
  const values: FormValues = {};
  for (const field of fields) {
    values[field.name] = field.type === "switch" ? true : "";
  }
  return values;
}

function rowToFormValues(fields: FieldConfig[], row: MasterDataRow): FormValues {
  const values: FormValues = {};
  for (const field of fields) {
    const raw = row[field.name];
    values[field.name] = field.type === "switch" ? Boolean(raw) : String(raw ?? "");
  }
  return values;
}

export function MasterDataCrud({ entity, entityLabel, fields, initialData }: MasterDataCrudProps) {
  const router = useRouter();
  const [dialogState, setDialogState] = React.useState<
    { mode: "create" } | { mode: "edit"; row: MasterDataRow } | null
  >(null);
  const [formValues, setFormValues] = React.useState<FormValues>({});
  const [error, setError] = React.useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = React.useState(false);

  function openCreate() {
    setFormValues(emptyFormValues(fields));
    setError(null);
    setDialogState({ mode: "create" });
  }

  function openEdit(row: MasterDataRow) {
    setFormValues(rowToFormValues(fields, row));
    setError(null);
    setDialogState({ mode: "edit", row });
  }

  async function toggleActive(row: MasterDataRow) {
    const response = await fetch(`/api/admin/${entity}/${encodeURIComponent(row.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !row.is_active }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      toast.error(body.detail ?? "Could not update status");
      return;
    }
    toast.success(row.is_active ? `${entityLabel} deactivated` : `${entityLabel} activated`);
    router.refresh();
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dialogState) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const isCreate = dialogState.mode === "create";
      const relevantFields = fields.filter((f) => isCreate || f.editable !== false);
      const payload: Record<string, unknown> = {};
      for (const field of relevantFields) {
        payload[field.name] = formValues[field.name];
      }
      // Product's `sku` is a second natural key the create form doesn't
      // expose separately — id and sku stay identical, matching the
      // baseline seeder's own id==sku convention (baseline_data.py). sku
      // never appears in ProductUpdate, so this only matters on create.
      if (entity === "products" && isCreate) {
        payload.sku = payload.id;
      }

      const url = isCreate
        ? `/api/admin/${entity}`
        : `/api/admin/${entity}/${encodeURIComponent(dialogState.row.id)}`;
      const response = await fetch(url, {
        method: isCreate ? "POST" : "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        setError(typeof body.detail === "string" ? body.detail : "Request failed");
        return;
      }
      toast.success(isCreate ? `${entityLabel} created` : `${entityLabel} updated`);
      setDialogState(null);
      router.refresh();
    } catch {
      setError("Could not reach the server");
    } finally {
      setIsSubmitting(false);
    }
  }

  const columns = React.useMemo<ColumnDef<MasterDataRow>[]>(() => {
    const dataColumns: ColumnDef<MasterDataRow>[] = fields
      .filter((field) => field.type !== "switch")
      .map((field) => ({
        accessorKey: field.name,
        header: ({ column }) => <SortableHeader column={column} title={field.label} />,
        cell: ({ row }) => {
          const value = row.original[field.name];
          if (field.type === "select") {
            const option = field.options?.find((o) => o.value === value);
            return option?.label ?? String(value ?? "");
          }
          return String(value ?? "");
        },
      }));

    return [
      ...dataColumns,
      {
        id: "status",
        header: "Status",
        cell: ({ row }) => (
          <Badge variant={row.original.is_active ? "default" : "secondary"}>
            {row.original.is_active ? "Active" : "Inactive"}
          </Badge>
        ),
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => openEdit(row.original)}>
              <IconPencil className="size-3.5" /> Edit
            </Button>
            <Button variant="outline" size="sm" onClick={() => toggleActive(row.original)}>
              {row.original.is_active ? "Deactivate" : "Activate"}
            </Button>
          </div>
        ),
      },
    ];
    // entity/entityLabel are static per page and openEdit/toggleActive are
    // recreated every render anyway (not memoized) — only `fields` ever
    // actually changes the shape of these columns.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fields]);

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={openCreate}>
          <IconPlus className="size-4" /> Add {entityLabel}
        </Button>
      </div>

      <DataTable columns={columns} data={initialData} searchKey={fields[0]?.name} searchPlaceholder={`Search ${entityLabel.toLowerCase()}s…`} />

      <Dialog open={dialogState !== null} onOpenChange={(open) => !open && setDialogState(null)}>
        <DialogContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>
                {dialogState?.mode === "create" ? `Add ${entityLabel}` : `Edit ${entityLabel}`}
              </DialogTitle>
              <DialogDescription>
                Edits take effect going forward — existing scenario/operational records that
                reference this {entityLabel.toLowerCase()} by id are never rewritten (PRD 5.6).
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              {fields.map((field) => {
                if (field.editable === false && dialogState?.mode === "edit") {
                  return null;
                }
                const value = formValues[field.name];

                if (field.type === "switch") {
                  return (
                    <div key={field.name} className="flex items-center justify-between">
                      <Label htmlFor={field.name}>{field.label}</Label>
                      <Switch
                        id={field.name}
                        checked={Boolean(value)}
                        onCheckedChange={(checked) =>
                          setFormValues((prev) => ({ ...prev, [field.name]: checked }))
                        }
                      />
                    </div>
                  );
                }

                if (field.type === "select") {
                  return (
                    <div key={field.name} className="space-y-1.5">
                      <Label htmlFor={field.name}>{field.label}</Label>
                      <Select
                        value={String(value ?? "")}
                        onValueChange={(v) =>
                          setFormValues((prev) => ({ ...prev, [field.name]: v }))
                        }
                      >
                        <SelectTrigger id={field.name} className="w-full">
                          <SelectValue placeholder={`Select ${field.label.toLowerCase()}`} />
                        </SelectTrigger>
                        <SelectContent>
                          {field.options?.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  );
                }

                return (
                  <div key={field.name} className="space-y-1.5">
                    <Label htmlFor={field.name}>{field.label}</Label>
                    <Input
                      id={field.name}
                      type={field.type === "text" ? "text" : "number"}
                      min={field.min}
                      max={field.max}
                      step={field.step ?? (field.type === "decimal" ? "0.01" : "1")}
                      value={String(value ?? "")}
                      onChange={(e) =>
                        setFormValues((prev) => ({ ...prev, [field.name]: e.target.value }))
                      }
                      disabled={field.editable === false && dialogState?.mode === "edit"}
                      required
                    />
                  </div>
                );
              })}
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}

            <DialogFooter>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
