import { listMasterData } from "@/lib/admin-api";
import { getCurrentRole } from "@/lib/current-user";
import { MasterDataCrud, type FieldConfig, type MasterDataRow } from "@/components/master-data-crud";

const FIELDS: FieldConfig[] = [
  { name: "id", label: "SKU", type: "text", editable: false },
  { name: "name", label: "Name", type: "text" },
  {
    name: "category",
    label: "Category",
    type: "select",
    options: [
      { value: "corrugated_packaging", label: "Corrugated Packaging" },
      { value: "protective_packaging", label: "Protective Packaging" },
      { value: "shipping_labeling_supplies", label: "Shipping/Labeling Supplies" },
    ],
  },
  { name: "unit_cost", label: "Unit Cost ($)", type: "decimal", min: 0, step: "0.01" },
  { name: "is_active", label: "Active", type: "switch" },
];

export default async function ProductsSettingsPage() {
  const [response, role] = await Promise.all([listMasterData("products"), getCurrentRole()]);
  const rows: MasterDataRow[] = response.ok ? await response.json() : [];

  return (
    <MasterDataCrud
      entity="products"
      entityLabel="Product"
      fields={FIELDS}
      initialData={rows}
      canWrite={role === "admin"}
    />
  );
}
