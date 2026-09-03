import { listMasterData } from "@/lib/admin-api";
import { getCurrentRole } from "@/lib/current-user";
import { MasterDataCrud, type FieldConfig, type MasterDataRow } from "@/components/master-data-crud";

const FIELDS: FieldConfig[] = [
  { name: "id", label: "ID", type: "text", editable: false },
  { name: "name", label: "Name", type: "text" },
  { name: "category_focus", label: "Category Focus", type: "text" },
  {
    name: "unit_cost_tier",
    label: "Cost Tier",
    type: "select",
    options: [
      { value: "low", label: "Low" },
      { value: "mid", label: "Mid" },
      { value: "high", label: "High" },
    ],
  },
  { name: "base_lead_time_days", label: "Base Lead Time (days)", type: "integer", min: 0 },
  {
    name: "lead_time_variability",
    label: "Lead Time Variability",
    type: "select",
    options: [
      { value: "low", label: "Low" },
      { value: "medium", label: "Medium" },
      { value: "high", label: "High" },
    ],
  },
  {
    name: "historical_otif_pct",
    label: "Historical OTIF (%)",
    type: "decimal",
    min: 0,
    max: 100,
    step: "0.01",
  },
  { name: "is_active", label: "Active", type: "switch" },
];

export default async function SuppliersSettingsPage() {
  const [response, role] = await Promise.all([listMasterData("suppliers"), getCurrentRole()]);
  const rows: MasterDataRow[] = response.ok ? await response.json() : [];

  return (
    <MasterDataCrud
      entity="suppliers"
      entityLabel="Supplier"
      fields={FIELDS}
      initialData={rows}
      canWrite={role === "admin"}
    />
  );
}
