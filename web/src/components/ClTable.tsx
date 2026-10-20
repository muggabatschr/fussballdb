import Link from "next/link";
import type { ClTableRow } from "@/lib/api";
import { num } from "@/lib/format";
import { PlaceDiff } from "./LeagueTable";
import { TeamName } from "./TeamName";

// Ligaphase: 1–8 direkt ins Achtelfinale, 9–24 Play-offs, 25–36 raus
const zone = (place: number) => (place <= 8 ? "border-l-home" : place <= 24 ? "border-l-accent/50" : "border-l-transparent");

export function ClLeagueTable({ rows }: { rows: ClTableRow[] }) {
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
            <th className="px-3 py-2 text-right" title="Punkte, die die Prognosen vor den gespielten Spielen erwarten ließen">
              Modell
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-b border-border last:border-b-0">
              <td className={`border-l-2 px-3 py-2 text-muted ${zone(r.platz)}`}>
                <span className="inline-flex items-baseline gap-1">
                  {r.platz}
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
              <td className="px-3 py-2 text-right text-muted">{r.modell_pkt != null ? num(r.modell_pkt, 1) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const pct = (v?: number) => (v == null ? "–" : v >= 99.95 ? ">99" : v > 0 && v < 0.5 ? "<1" : num(v, 0));

/** Geschätzte Abschlusstabelle der Ligaphase (10.000 Simulationen der offenen Spiele). */
export function ClProjectionTable({ rows }: { rows: ClTableRow[] }) {
  const projected = rows.filter((r) => r.prognose_platz != null).sort((a, b) => a.prognose_platz! - b.prognose_platz!);
  if (!projected.length) return null;
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm tabular [&_td]:whitespace-nowrap">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Team</th>
            <th className="px-3 py-2 text-right" title="Erwartete Punkte nach dem 8. Spieltag">Pkt</th>
            <th className="px-3 py-2 text-right" title="Platz heute">heute</th>
            <th className="px-3 py-2 text-right" title="Chance auf Platz 1–8 (direkt ins Achtelfinale)">AF</th>
            <th className="px-3 py-2 text-right" title="Chance auf Platz 9–24 (Play-offs)">Play-offs</th>
            <th className="px-3 py-2 text-right" title="Chance auf Platz 25–36 (ausgeschieden)">Aus</th>
          </tr>
        </thead>
        <tbody>
          {projected.map((r) => (
            <tr key={r.name} className="border-b border-border last:border-b-0">
              <td className={`border-l-2 px-3 py-2 text-muted ${zone(r.prognose_platz!)}`}>{r.prognose_platz}</td>
              <td className="px-3 py-2">
                <TeamName name={r.name} />
              </td>
              <td className="px-3 py-2 text-right font-semibold">{num(r.erw_punkte ?? 0, 0)}</td>
              <td className="px-3 py-2 text-right text-muted">{r.platz}</td>
              <td className="px-3 py-2 text-right">{pct(r.p_achtelfinale)} %</td>
              <td className="px-3 py-2 text-right">{pct(r.p_playoffs)} %</td>
              <td className="px-3 py-2 text-right">{pct(r.p_aus)} %</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Saisonwahl für die CL-Tabelle. */
export function ClTableSeasons({ seasons, current }: { seasons: { season: number; label: string }[]; current: number }) {
  return (
    <div className="flex gap-2 text-sm">
      {seasons.map((s) => (
        <Link
          key={s.season}
          href={`/cl/tabelle/${s.season}`}
          className={`rounded-lg border px-3 py-1.5 ${s.season === current ? "border-accent" : "border-border bg-surface hover:border-accent"}`}
        >
          {s.label}
        </Link>
      ))}
    </div>
  );
}
