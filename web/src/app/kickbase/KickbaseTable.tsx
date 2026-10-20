"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Card } from "@/components/Card";
import { TeamLogo } from "@/components/TeamLogo";
import { TeamName } from "@/components/TeamName";
import type { KickbaseRow } from "@/lib/api";
import { num } from "@/lib/format";

const POSITIONS = ["alle", "TW", "ABW", "MF", "ST"] as const;
const SCOPES = { alle: "alle Spieler", markt: "nur Transfermarkt", kader: "nur mein Kader" } as const;
type SortKey = "kb_punkte" | "punkte_pro_mio" | "marktwert" | "trend_7t" | "einsatz" | "tore" | "vorlagen" | "zu_null";
const COLUMNS: { key: SortKey; label: string; title: string; fmt: (v: number) => string }[] = [
  { key: "kb_punkte", label: "Erw. Pkt", title: "Erwartete Kickbase-Punkte über die gewählten Spieltage", fmt: (v) => num(v, 0) },
  { key: "punkte_pro_mio", label: "Pkt/Mio", title: "Erwartete Punkte je Million Marktwert", fmt: (v) => num(v, 1) },
  { key: "marktwert", label: "Marktwert", title: "Aktueller Kickbase-Marktwert", fmt: (v) => `${num(v / 1e6, 1)} Mio` },
  { key: "trend_7t", label: "Trend 7T", title: "Marktwert-Änderung der letzten 7 Tage", fmt: (v) => `${v > 0 ? "+" : ""}${num(v * 100, 1)} %` },
  { key: "einsatz", label: "Einsatz", title: "Chance auf Startelf (Ø über die Spieltage)", fmt: (v) => `${Math.round(v * 100)} %` },
  { key: "tore", label: "Tore", title: "Erwartete Tore", fmt: (v) => num(v, 2) },
  { key: "vorlagen", label: "Vorl.", title: "Erwartete Vorlagen", fmt: (v) => num(v, 2) },
  { key: "zu_null", label: "Zu null", title: "Erwartete Spiele ohne Gegentor (Torwart und Abwehr)", fmt: (v) => num(v, 2) },
];

const mio = (v: number | null) => (v == null ? "–" : `${num(v / 1e6, 1)} Mio`);

function sellReasons(r: KickbaseRow, median: number): string[] {
  const out: string[] = [];
  if (r.ausfall === "suspension") out.push("gesperrt");
  else if (r.ausfall) out.push("verletzt");
  else if (r.einsatz < 0.5) out.push(`Einsatz unsicher (${Math.round(r.einsatz * 100)} %)`);
  if (r.trend_7t != null && r.trend_7t < -0.02) out.push(`Marktwert fällt (${num(r.trend_7t * 100, 1)} %)`);
  if (r.kb_punkte != null && r.kb_punkte < median * 0.6) out.push("wenig erwartete Punkte");
  return out;
}

export function KickbaseTable({ rows, matchdays }: { rows: KickbaseRow[]; matchdays: number }) {
  const router = useRouter();
  const [pos, setPos] = useState<(typeof POSITIONS)[number]>("alle");
  const [scope, setScope] = useState<keyof typeof SCOPES>("alle");
  const [sort, setSort] = useState<SortKey>("kb_punkte");
  const [hideOut, setHideOut] = useState(true);

  const withKb = rows.filter((r) => r.kb_punkte != null);
  const median = useMemo(() => {
    const v = withKb.filter((r) => r.einsatz >= 0.5).map((r) => r.kb_punkte!).sort((a, b) => a - b);
    return v.length ? v[Math.floor(v.length / 2)] : 0;
  }, [withKb]);
  const buy = withKb
    // eigene Spieler, die du selbst auf den Markt gestellt hast, sind keine Kaufkandidaten
    .filter((r) => r.markt_preis != null && !r.im_kader && !r.ausfall && r.einsatz >= 0.5 && r.punkte_pro_mio != null)
    .sort((a, b) => b.punkte_pro_mio! - a.punkte_pro_mio!)
    .slice(0, 5);
  const sell = withKb
    .filter((r) => r.im_kader)
    .map((r) => ({ r, reasons: sellReasons(r, median) }))
    .filter((x) => x.reasons.length)
    .sort((a, b) => b.reasons.length - a.reasons.length || (a.r.kb_punkte ?? 0) - (b.r.kb_punkte ?? 0))
    .slice(0, 5);

  const shown = useMemo(() => {
    let r = rows;
    if (pos !== "alle") r = r.filter((x) => x.position === pos);
    if (scope === "markt") r = r.filter((x) => x.markt_preis != null);
    if (scope === "kader") r = r.filter((x) => x.im_kader);
    if (hideOut && scope === "alle") r = r.filter((x) => !x.ausfall && x.einsatz > 0.05);
    return [...r].sort((a, b) => (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity)).slice(0, 200);
  }, [rows, pos, scope, sort, hideOut]);

  const select = "rounded-lg border border-border bg-surface px-3 py-1.5 text-sm";
  const horizon = matchdays === 1 ? "nächster Spieltag" : `nächste ${matchdays} Spieltage`;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <h2 className="mb-2 whitespace-nowrap text-sm font-medium">Kaufkandidaten auf eurem Markt</h2>
          {buy.length ? (
            <ul className="space-y-1.5 text-sm">
              {buy.map((r) => (
                <li key={r.player_id} className="flex items-center justify-between gap-2 whitespace-nowrap">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <TeamLogo name={r.team_name} size={16} />
                    <span className="truncate">{r.name}</span>
                    <span className="text-xs text-muted">{r.position}</span>
                  </span>
                  <span className="shrink-0 text-xs text-muted tabular">
                    <span className="font-semibold text-foreground">{num(r.kb_punkte!, 0)} Pkt</span> · {num(r.punkte_pro_mio!, 1)}/Mio ·{" "}
                    {mio(r.markt_preis)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Keine einsatzfähigen Spieler mit Kickbase-Daten auf dem Markt.</p>
          )}
        </Card>
        <Card>
          <h2 className="mb-2 whitespace-nowrap text-sm font-medium">Verkaufskandidaten in deinem Kader</h2>
          {sell.length ? (
            <ul className="space-y-1.5 text-sm">
              {sell.map(({ r, reasons }) => (
                <li key={r.player_id} className="flex items-center justify-between gap-2 whitespace-nowrap">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <TeamLogo name={r.team_name} size={16} />
                    <span className="truncate">{r.name}</span>
                  </span>
                  <span className="truncate text-xs text-away" title={reasons.join(", ")}>{reasons.join(", ")}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Kein Spieler deines Kaders fällt auf.</p>
          )}
        </Card>
      </div>

      <div className="flex flex-wrap items-center gap-2 [&>*]:shrink-0">
        <select aria-label="Spieltage" className={select} value={matchdays}
          onChange={(e) => router.push(`/kickbase?spieltage=${e.target.value}`)}>
          {[1, 2, 3, 5].map((n) => (
            <option key={n} value={n}>{n === 1 ? "nächster Spieltag" : `nächste ${n} Spieltage`}</option>
          ))}
        </select>
        <select aria-label="Auswahl" className={select} value={scope} onChange={(e) => setScope(e.target.value as keyof typeof SCOPES)}>
          {Object.entries(SCOPES).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <select aria-label="Position" className={select} value={pos} onChange={(e) => setPos(e.target.value as typeof pos)}>
          {POSITIONS.map((p) => (
            <option key={p} value={p}>{p === "alle" ? "alle Positionen" : p}</option>
          ))}
        </select>
        {scope === "alle" && (
          <label className="flex items-center gap-1.5 whitespace-nowrap text-sm text-muted">
            <input type="checkbox" checked={hideOut} onChange={(e) => setHideOut(e.target.checked)} />
            Ausfälle ausblenden
          </label>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full text-sm tabular [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
          <thead className="text-left text-xs text-muted">
            <tr className="border-b border-border">
              <th className="px-3 py-2">Spieler</th>
              <th className="px-3 py-2">Pos.</th>
              <th className="px-3 py-2">Gegner</th>
              {COLUMNS.map((c) => (
                <th key={c.key} className="px-3 py-2 text-right" title={c.title}>
                  <button onClick={() => setSort(c.key)} className={sort === c.key ? "text-foreground" : "hover:text-foreground"}>
                    {c.label}{sort === c.key ? " ↓" : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.player_id} className="border-b border-border last:border-0">
                <td className="max-w-64 px-3 py-2">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <TeamLogo name={r.team_name} size={16} />
                    <span className="truncate font-medium" title={r.name}>{r.name}</span>
                    {r.ausfall && (
                      <span className="shrink-0 rounded bg-away/15 px-1 text-xs text-away">
                        {r.ausfall === "suspension" ? "gesperrt" : "verletzt"}
                      </span>
                    )}
                    {r.im_kader && (
                      <span className="shrink-0 rounded bg-accent/15 px-1 text-xs text-accent">
                        {r.markt_preis != null ? "Kader, angeboten" : "Kader"}
                      </span>
                    )}
                    {r.markt_preis != null && !r.im_kader && (
                      <span className="shrink-0 rounded bg-home/15 px-1 text-xs text-home" title={`Auf eurem Transfermarkt für ${mio(r.markt_preis)}`}>
                        Markt
                      </span>
                    )}
                  </span>
                </td>
                <td className="px-3 py-2 text-muted">{r.position}</td>
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5">
                    {r.gegner.map((g, i) => (
                      <span key={i} className="inline-flex items-center gap-1" title={`${r.heim[i] ? "Heim" : "Auswärts"} gegen ${g}`}>
                        <span className="text-xs text-muted">{r.heim[i] ? "H" : "A"}</span>
                        {r.gegner.length === 1 ? <TeamName name={g} short link={false} logoSize={16} /> : <TeamLogo name={g} size={16} />}
                      </span>
                    ))}
                  </span>
                </td>
                {COLUMNS.map((c) => {
                  const v = r[c.key];
                  const color = c.key === "trend_7t" && v != null ? (v > 0.005 ? "text-home" : v < -0.005 ? "text-away" : "") : "";
                  return (
                    <td key={c.key} className={`px-3 py-2 text-right ${sort === c.key ? "font-semibold" : ""} ${color}`}>
                      {v == null ? "–" : c.fmt(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        Erwartete Kickbase-Punkte für {horizon}: Modell aus echten Kickbase-Punkten (Einsatz, Tore, Vorlagen, Gegentore,
        zu null, Sieg/Remis, Karten je Position plus Spielerwert), mit den erwarteten Ereignissen jedes Spiels.
        Marktwerte und Markt deiner Liga aus deinem Kickbase-Zugang.
      </p>
    </div>
  );
}
