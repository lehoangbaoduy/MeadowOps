import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Unit 38 (MEADOWOPS-DOM-026): the plain-language story of the scenario, for
 * the Builder. Free text rendered as a plain JSX text node (React escapes
 * it), whitespace-preserved so paragraphs survive.
 */
export function NarrativeCard({ narrative }: { narrative: string }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">Scenario narrative</CardTitle>
          <Badge variant="secondary">Builder only</Badge>
        </div>
        <CardDescription>What is going on in this scenario, in plain language.</CardDescription>
      </CardHeader>
      <CardContent>
        {narrative ? (
          <p className="max-w-prose text-sm leading-relaxed whitespace-pre-wrap">{narrative}</p>
        ) : (
          <p className="text-sm italic text-muted-foreground">
            No narrative yet. Add one below, or regenerate the scenario to have it drafted.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
