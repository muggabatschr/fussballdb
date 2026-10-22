"use client";

import type { ToolUIPart } from "ai";
import { AbsenceList } from "@/components/AbsenceList";
import { FormTable } from "@/components/FormTable";
import { LeagueTable } from "@/components/LeagueTable";
import { PredictionCard } from "@/components/PredictionCard";
import { TipSheet } from "@/components/TipSheet";
import type { ChatTools } from "@/app/api/chat/tools";

const labels: Record<keyof ChatTools, string> = {
  get_upcoming_matches: "Lade kommende Spiele",
  get_team_form: "Lade Form",
  get_head_to_head: "Lade direkte Duelle",
  predict_match: "Berechne Prognose",
  get_absences: "Lade Ausfälle",
  get_table: "Lade Tabelle",
  get_tip_sheet: "Lade Tipp-Zettel",
  run_sql: "Frage Datenbank ab",
};

type Part = ToolUIPart<ChatTools>;

export function ToolResult({ part }: { part: Part }) {
  const name = part.type.slice(5) as keyof ChatTools;
  if (part.state === "input-streaming" || part.state === "input-available") {
    return <p className="text-xs text-muted">{labels[name] ?? name} …</p>;
  }
  if (part.state === "output-error") {
    return <p className="text-xs text-away">Werkzeug {name} fehlgeschlagen: {part.errorText}</p>;
  }
  if (part.state !== "output-available") return null;

  switch (part.type) {
    case "tool-predict_match":
      return <PredictionCard home={part.output.home} away={part.output.away} p={part.output} />;
    case "tool-get_team_form":
      return (
        <div>
          <p className="mb-1 text-xs text-muted">Form {part.output.team}</p>
          <FormTable games={part.output.spiele} />
        </div>
      );
    case "tool-get_absences":
      return (
        <div>
          <p className="mb-1 text-xs text-muted">Ausfälle {part.output.team}</p>
          <AbsenceList rows={part.output.ausfaelle} />
        </div>
      );
    case "tool-get_table":
      return <LeagueTable rows={part.output} />;
    case "tool-get_tip_sheet":
      return <TipSheet {...part.output} compact />;
    default:
      return (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer">Daten: {name}</summary>
          <pre className="mt-1 max-h-64 overflow-auto rounded bg-surface p-2">{JSON.stringify(part.output, null, 2)}</pre>
        </details>
      );
  }
}
