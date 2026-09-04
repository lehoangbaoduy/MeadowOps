"use client"

import { useState } from "react"
import { Send } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { PERSONAS, personaLabel, type Persona, type ScenarioOption } from "../data"

export function NewThreadDialog({
  scenarios,
  onCreate,
}: {
  scenarios: ScenarioOption[];
  onCreate: (scenarioId: string, persona: Persona) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [scenarioId, setScenarioId] = useState<string>("");
  const [persona, setPersona] = useState<Persona | "">("");
  const [creating, setCreating] = useState(false);

  async function handleCreate() {
    if (!scenarioId || !persona || creating) return;
    setCreating(true);
    try {
      await onCreate(scenarioId, persona);
      setOpen(false);
      setScenarioId("");
      setPersona("");
    } finally {
      setCreating(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="w-full cursor-pointer">
          New thread
          <Send className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Open a persona thread</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="scenario">Scenario</Label>
            <Select value={scenarioId} onValueChange={setScenarioId}>
              <SelectTrigger id="scenario" className="cursor-pointer">
                <SelectValue placeholder="Select an active scenario" />
              </SelectTrigger>
              <SelectContent>
                {scenarios.map((scenario) => (
                  <SelectItem key={scenario.id} value={scenario.id} className="cursor-pointer">
                    {scenario.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="persona">Persona</Label>
            <Select value={persona} onValueChange={(value) => setPersona(value as Persona)}>
              <SelectTrigger id="persona" className="cursor-pointer">
                <SelectValue placeholder="Select a stakeholder persona" />
              </SelectTrigger>
              <SelectContent>
                {PERSONAS.map((option) => (
                  <SelectItem key={option} value={option} className="cursor-pointer">
                    {personaLabel(option)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button
            onClick={handleCreate}
            disabled={!scenarioId || !persona || creating}
            className="cursor-pointer"
          >
            Open thread
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
