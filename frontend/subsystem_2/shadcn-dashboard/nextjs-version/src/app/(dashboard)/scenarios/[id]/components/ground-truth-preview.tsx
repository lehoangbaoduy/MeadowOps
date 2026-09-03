import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { ScenarioGroundTruth } from "../../types";

function TextList({ items }: { items: string[] }) {
  if (items.length === 0) {
    return <p className="text-sm italic text-muted-foreground">Not filled in yet.</p>;
  }
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((item, i) => (
        // Ground-truth list items are Builder-authored free text — rendered
        // as plain JSX text nodes only (React escapes by default), never
        // via dangerouslySetInnerHTML or a raw-HTML-passthrough markdown
        // renderer (pre-implementation security review of this unit).
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

/**
 * Unit 20a (MEADOWOPS-UI-002): the "preview" screen (pre-scoping decision,
 * this unit) — a formatted narrative, splitting the Builder-editable
 * ground_truth fields from the mechanically-derived `evidence`/provenance
 * block, never raw JSON. `evidence`'s own field names are fixed by
 * app.domain.scenario.build_ground_truth_from_exception_flag and rendered
 * as plain text values, not dumped as a JSON blob either.
 */
export function GroundTruthPreview({ groundTruth }: { groundTruth: ScenarioGroundTruth }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Narrative (Builder-editable)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-xs font-medium text-muted-foreground">Known cause</p>
            <p className="text-sm">{groundTruth.known_cause || (
              <span className="italic text-muted-foreground">Not filled in yet.</span>
            )}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Supporting signals</p>
            <TextList items={groundTruth.supporting_signals} />
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Distractors</p>
            <TextList items={groundTruth.distractors} />
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Expected considerations</p>
            <TextList items={groundTruth.expected_considerations} />
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Acceptable conclusions</p>
            <TextList items={groundTruth.acceptable_conclusions} />
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Unacceptable conclusions</p>
            <TextList items={groundTruth.unacceptable_conclusions} />
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Uncertainty</p>
            <p className="text-sm">{groundTruth.uncertainty || (
              <span className="italic text-muted-foreground">Not filled in yet.</span>
            )}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Provenance (mechanically derived)</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Source exception flag</dt>
            <dd className="font-mono text-xs">{groundTruth.evidence.source_exception_flag_id}</dd>
            <dt className="text-muted-foreground">Category</dt>
            <dd>{groundTruth.evidence.category}</dd>
            <dt className="text-muted-foreground">Product</dt>
            <dd>{groundTruth.evidence.product_id ?? "—"}</dd>
            <dt className="text-muted-foreground">Warehouse</dt>
            <dd>{groundTruth.evidence.warehouse_id ?? "—"}</dd>
            <dt className="text-muted-foreground">Measured value</dt>
            <dd>{groundTruth.evidence.measured_value ?? "—"}</dd>
            <dt className="text-muted-foreground">Threshold value</dt>
            <dd>{groundTruth.evidence.threshold_value}</dd>
            <dt className="text-muted-foreground">First detected</dt>
            <dd>{groundTruth.evidence.first_detected_simulation_date}</dd>
            <dt className="text-muted-foreground">Simulation date</dt>
            <dd>{groundTruth.evidence.simulation_date}</dd>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
