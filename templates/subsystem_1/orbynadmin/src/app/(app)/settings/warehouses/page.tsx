import { listMasterData } from "@/lib/admin-api";
import { MasterDataCrud, type FieldConfig, type MasterDataRow } from "@/components/master-data-crud";

const FIELDS: FieldConfig[] = [
  { name: "id", label: "ID", type: "text", editable: false },
  { name: "name", label: "Name", type: "text" },
  { name: "region", label: "Region", type: "text" },
  { name: "capacity_pallet_positions", label: "Capacity (pallet positions)", type: "integer", min: 0 },
  { name: "is_active", label: "Active", type: "switch" },
];

export default async function WarehousesSettingsPage() {
  const response = await listMasterData("warehouses");
  const rows: MasterDataRow[] = response.ok ? await response.json() : [];

  return (
    <MasterDataCrud entity="warehouses" entityLabel="Warehouse" fields={FIELDS} initialData={rows} />
  );
}
