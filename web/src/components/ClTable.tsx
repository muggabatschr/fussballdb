import Link from "next/link";
import type { ClTableRow, TableZone } from "@/lib/api";
import { num } from "@/lib/format";
import { PlaceDiff } from "./LeagueTable";
import { TeamName } from "./TeamName";

const CL_ZONES: TableZone[] = [
  { key: "p_achtelfinale", label: "AF", von: 1, bis: 8 },
  { key: "p_playoffs", label: "Play-offs", von: 9, bis: 24 },
  { key: "p_aus", label: "Aus", von: 25, bis: 36 },
];

// Randfarbe je Zone: erste Zone grün (Achtelfinale, Aufstieg), Abstieg rot, sonst neutral
function zoneClass(place: number, zones: TableZone[]): string {
  const z = zones.find((x) => place >= x.von && place <= x.bis);
  if (!z) return "border-l-transparent";
  if (z === zones[0]) return "border-l-home";
  if (/abstieg/i.test(z.label)) return "border-l-away";
  if (/aus/i.test(z.label)) return "border-l-transparent";
  return "border-l-accent/50";
}

export function ClLeagueTable({ rows, zones = CL_ZONES }: { rows: ClTableRow[]; zones?: TableZone[] }) {
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
              <td className={`border-l-2 px-3 py-2 text-muted ${zoneClass(r.platz, zones)}`}>
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

/** Geschätzte Abschlusstabelle (10.000 Simulationen der offenen Spiele) mit den Zonen-Chancen. */
export function ClProjectionTable({ rows, zones = CL_ZONES }: { rows: ClTableRow[]; zones?: TableZone[] }) {
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
            {zones.map((z) => (
              <th key={z.key} className="px-3 py-2 text-right" title={`Chance auf Platz ${z.von}${z.bis > z.von ? `–${z.bis}` : ""}`}>
                {z.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {projected.map((r) => (
            <tr key={r.name} className="border-b border-border last:border-b-0">
              <td className={`border-l-2 px-3 py-2 text-muted ${zoneClass(r.prognose_platz!, zones)}`}>{r.prognose_platz}</td>
              <td className="px-3 py-2">
                <TeamName name={r.name} />
              </td>
              <td className="px-3 py-2 text-right font-semibold">{num(r.erw_punkte ?? 0, 0)}</td>
              <td className="px-3 py-2 text-right text-muted">{r.platz}</td>
              {zones.map((z) => (
                <td key={z.key} className="px-3 py-2 text-right">
                  {pct((r as Record<string, unknown>)[z.key] as number | undefined)} %
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Saisonwahl für die Tabelle. */
export function ClTableSeasons({ seasons, current, base = "/cl" }: { seasons: { season: number; label: string }[]; current: number; base?: string }) {
  return (
    <div className="flex gap-2 text-sm">
      {seasons.map((s) => (
        <Link
          key={s.season}
          href={`${base}/tabelle/${s.season}`}
          className={`rounded-lg border px-3 py-1.5 ${s.season === current ? "border-accent" : "border-border bg-surface hover:border-accent"}`}
        >
          {s.label}
        </Link>
      ))}
    </div>
  );
}
