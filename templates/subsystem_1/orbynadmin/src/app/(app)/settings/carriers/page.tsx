import { listMasterData } from "@/lib/admin-api";
import { MasterDataCrud, type FieldConfig, type MasterDataRow } from "@/components/master-data-crud";

const FIELDS: FieldConfig[] = [
  { name: "id", label: "ID", type: "text", editable: false },
  { name: "name", label: "Name", type: "text" },
  { name: "transit_days_min", label: "Transit Days (min)", type: "decimal", min: 0, step: "0.1" },
  { name: "transit_days_max", label: "Transit Days (max)", type: "decimal", min: 0, step: "0.1" },
  {
    name: "variability",
    label: "Variability",
    type: "select",
    options: [
      { value: "low", label: "Low" },
      { value: "medium", label: "Medium" },
      { value: "high", label: "High" },
    ],
  },
  {
    name: "reliability_pct",
    label: "Reliability (%)",
    type: "decimal",
    min: 0,
    max: 100,
    step: "0.01",
  },
  { name: "is_active", label: "Active", type: "switch" },
];

export default async function CarriersSettingsPage() {
  const response = await listMasterData("carriers");
  const rows: MasterDataRow[] = response.ok ? await response.json() : [];

  return (
    <MasterDataCrud entity="carriers" entityLabel="Carrier" fields={FIELDS} initialData={rows} />
  );
}
