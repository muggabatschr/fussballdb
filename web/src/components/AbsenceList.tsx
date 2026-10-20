import type { Absence } from "@/lib/api";
import { pct } from "@/lib/format";

export function AbsenceList({ rows }: { rows: Absence[] }) {
  if (!rows.length) return <p className="text-sm text-muted">Keine bekannten Ausfälle.</p>;
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
      {rows.map((a) => (
        <li key={`${a.player_name}-${a.kind}`} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
          <span>
            <span className="font-medium">{a.player_name}</span>
            {a.stammspieler && <span className="ml-2 rounded bg-away/15 px-1.5 text-xs text-away">Stammspieler</span>}
          </span>
          <span className="text-xs text-muted tabular">
            {a.kind === "suspension" ? "Sperre" : a.reason ?? "Verletzung"}
            {a.expected_return ? ` · bis ${a.expected_return}` : ""}
            {a.anteil_xg_xa != null ? ` · ${pct(a.anteil_xg_xa)} der xG+xA` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
