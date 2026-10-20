import type { TableRow } from "@/lib/api";
import { num } from "@/lib/format";
import { TeamName } from "./TeamName";

/** Plätze besser (+) oder schlechter (−) als laut Prognosen für die gespielten Spiele erwartet. */
function PlaceDiff({ r }: { r: TableRow }) {
  if (r.platz_diff == null || r.modell_platz == null) return null;
  const d = r.platz_diff;
  const title = `Laut Prognosen vor den Spielen erwartet: ${num(r.modell_pkt ?? 0, 1)} Punkte, Platz ${r.modell_platz}`;
  if (d === 0) return <span className="text-[10px] text-muted" title={title}>±0</span>;
  return (
    <span className={`text-[10px] font-semibold ${d > 0 ? "text-home" : "text-away"}`} title={title}>
      {d > 0 ? `+${d}` : `−${-d}`}
    </span>
  );
}

export function LeagueTable({ rows }: { rows: TableRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm tabular [&_td]:whitespace-nowrap">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Team</th>
            <th className="px-3 py-2 text-right">Sp</th>
            <th className="px-3 py-2 text-right">Tore</th>
            <th className="px-3 py-2 text-right">Pkt</th>
            <th className="px-3 py-2 text-right" title="Expected Goals">xG</th>
            <th className="px-3 py-2 text-right" title="Expected Goals gegen">xGA</th>
            <th className="px-3 py-2 text-right" title="Erwartete Punkte laut xG">xPts</th>
            <th className="px-3 py-2 text-right" title="Punkte minus erwartete Punkte">Pkt − xPts</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const diff = r.pkt - r.xpts;
            return (
              <tr key={r.name} className="border-b border-border last:border-0">
                <td className="px-3 py-2 text-muted">
                  <span className="inline-flex items-baseline gap-1">
                    {i + 1}
                    <PlaceDiff r={r} />
                  </span>
                </td>
                <td className="px-3 py-2">
                  <TeamName name={r.name} />
                </td>
                <td className="px-3 py-2 text-right">{r.sp}</td>
                <td className="px-3 py-2 text-right">
                  {r.tore}:{r.gegentore}
                </td>
                <td className="px-3 py-2 text-right font-semibold">{r.pkt}</td>
                <td className="px-3 py-2 text-right">{num(r.xg, 1)}</td>
                <td className="px-3 py-2 text-right">{num(r.xga, 1)}</td>
                <td className="px-3 py-2 text-right">{num(r.xpts, 1)}</td>
                <td className={`px-3 py-2 text-right ${diff > 0 ? "text-home" : "text-away"}`}>
                  {diff > 0 ? "+" : ""}
                  {num(diff, 1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Geschätzte Abschlusstabelle: offene Spiele 10.000-mal mit den Modell-Wahrscheinlichkeiten durchgespielt. */
export function ProjectionTable({ rows }: { rows: TableRow[] }) {
  const projected = rows.filter((r) => r.prognose_platz != null).sort((a, b) => a.prognose_platz! - b.prognose_platz!);
  if (!projected.length) return null;
  const pct = (v?: number) => (v == null ? "–" : v >= 99.95 ? ">99" : v > 0 && v < 0.5 ? "<1" : num(v, 0));
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm tabular [&_td]:whitespace-nowrap">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Team</th>
            <th className="px-3 py-2 text-right" title="Erwartete Punkte am Saisonende">Pkt</th>
            <th className="px-3 py-2 text-right" title="Platz heute">heute</th>
            <th className="px-3 py-2 text-right" title="Chance auf die Meisterschaft">Meister</th>
            <th className="px-3 py-2 text-right" title="Chance auf Platz 1–4">Top 4</th>
            <th className="px-3 py-2 text-right" title="Chance auf Platz 17–18">Abstieg</th>
          </tr>
        </thead>
        <tbody>
          {projected.map((r) => {
            const today = rows.indexOf(r) + 1;
            return (
              <tr key={r.name} className="border-b border-border last:border-0">
                <td className="px-3 py-2 text-muted">{r.prognose_platz}</td>
                <td className="px-3 py-2">
                  <TeamName name={r.name} />
                </td>
                <td className="px-3 py-2 text-right font-semibold">{num(r.erw_punkte ?? 0, 0)}</td>
                <td className="px-3 py-2 text-right text-muted">{today}</td>
                <td className="px-3 py-2 text-right">{pct(r.p_meister)} %</td>
                <td className="px-3 py-2 text-right">{pct(r.p_top4)} %</td>
                <td className="px-3 py-2 text-right">{pct(r.p_abstieg)} %</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
