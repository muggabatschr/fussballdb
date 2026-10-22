import type { FormGame } from "@/lib/api";
import { num } from "@/lib/format";
import { TeamName } from "./TeamName";

const result = (g: FormGame) => (g.tore > g.gegentore ? "S" : g.tore === g.gegentore ? "U" : "N");
const resultClass = { S: "bg-home text-white", U: "bg-draw text-white", N: "bg-away text-white" };

/** Letzte Spiele eines Teams. Mit `active`/`onActive` wird die Zeile unter der Maus gemeldet und die aktive
 * Zeile hervorgehoben (zusammen mit dem xG-Diagramm, siehe TeamGames). */
export function FormTable({
  games,
  active = null,
  onActive,
}: {
  games: FormGame[];
  active?: number | null;
  onActive?: (index: number | null) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm tabular [&_td]:whitespace-nowrap">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2">Datum</th>
            <th className="px-3 py-2">Gegner</th>
            <th className="px-3 py-2 text-center">Erg.</th>
            <th className="px-3 py-2 text-right">xG</th>
            <th className="px-3 py-2 text-right">Schüsse</th>
            <th className="px-3 py-2 text-right" title="Schüsse mit xG ≥ 0,3">Großchancen</th>
            <th className="px-3 py-2 text-right" title="Gegnerische Pässe je eigener Defensivaktion, niedriger = mehr Pressing">PPDA</th>
          </tr>
        </thead>
        <tbody>
          {games.map((g, i) => {
            const r = result(g);
            return (
              <tr
                key={`${g.datum}-${g.gegner}`}
                className={`border-b border-border transition-colors last:border-0 ${active === i ? "bg-accent/20" : ""}`}
                onMouseEnter={onActive && (() => onActive(i))}
                onMouseLeave={onActive && (() => onActive(null))}
              >
                <td className="px-3 py-2 text-muted">{new Date(g.datum).toLocaleDateString("de-DE")}</td>
                <td className="px-3 py-2">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-6 text-muted">{g.ort === "H" ? "vs." : "@"}</span>
                    <TeamName name={g.gegner} short logoSize={16} />
                  </span>
                </td>
                <td className="px-3 py-2 text-center">
                  <span className={`inline-block w-12 rounded px-1 text-xs ${resultClass[r]}`}>
                    {g.tore}:{g.gegentore}
                  </span>
                </td>
                <td className="px-3 py-2 text-right">
                  {num(g.xg)} : {num(g.xga)}
                </td>
                <td className="px-3 py-2 text-right">
                  {g.shots ?? "–"} : {g.shots_against ?? "–"}
                </td>
                <td className="px-3 py-2 text-right">
                  {g.big_chances ?? "–"} : {g.big_chances_against ?? "–"}
                </td>
                <td className="px-3 py-2 text-right">{num(g.ppda, 1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
