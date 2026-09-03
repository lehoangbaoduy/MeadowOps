import { PageHeader } from "@/components/page-header";
import { QueryPlayground } from "@/components/query-playground";

export default function QueryPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Query"
        description="Free-form SQL against a sandboxed replica of the operational schema — safe to experiment with."
      />
      <QueryPlayground />
    </div>
  );
}
