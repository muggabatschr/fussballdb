import Link from "next/link";
import type { DetailAbsence, DetailFormGame, DetailH2H, MatchDetail, MatchStats, Scorer, TipRound } from "@/lib/api";
import { kickoff, num, pct } from "@/lib/format";
import { shortName } from "@/lib/teams";
import { Card } from "./Card";
import { Legend, TERMS } from "./Legend";
import { lastName, TvLine } from "./MatchdayView";
import { ProbabilityBar } from "./ProbabilityBar";
import { TeamName } from "./TeamName";
import { TipRoundSelect } from "./TipRoundSelect";
import { VenueLine } from "./VenueLine";

const result = (own: number, opp: number) => (own > opp ? "S" : own === opp ? "U" : "N");
const resultClass = { S: "bg-home text-white dark:text-black", U: "bg-draw text-white", N: "bg-away text-white dark:text-black" };
const date = (iso: string) =>
  new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "2-digit", timeZone: "Europe/Berlin" });
const mio = (v: number | null | undefined) =>
  v == null ? "–" : v >= 1e9 ? `${num(v / 1e9, 2)} Mrd. €` : `${num(v / 1e6, v >= 1e8 ? 0 : 1)} Mio. €`;

function Section({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 ${className}`}>
      <h2 className="mb-2 text-sm font-medium">{title}</h2>
      {children}
    </section>
  );
}

/** Zwei Spalten Heim | Gast, auf dem Handy untereinander, jeweils mit Wappen und Namen darüber. */
function Sides<T>({ home, away, data, render }: { home: string; away: string; data: { home: T; away: T }; render: (v: T) => React.ReactNode }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {(["home", "away"] as const).map((side) => (
        <Card key={side} className="min-w-0 space-y-2">
          <div className="text-sm font-medium">
            <TeamName name={side === "home" ? home : away} logoSize={18} />
          </div>
          {render(data[side])}
        </Card>
      ))}
    </div>
  );
}

function ResultChip({ own, opp }: { own: number; opp: number }) {
  const r = result(own, opp);
  return <span className={`inline-block w-11 shrink-0 rounded px-1 text-center text-xs tabular ${resultClass[r]}`}>{own}:{opp}</span>;
}

function FormList({ games }: { games: DetailFormGame[] }) {
  if (!games.length) return <p className="text-sm text-muted">Keine Spiele vor diesem Spiel in der Datenbank.</p>;
  const pts = games.reduce((s, g) => s + (g.tore > g.gegentore ? 3 : g.tore === g.gegentore ? 1 : 0), 0);
  return (
    <>
      <div className="flex items-center gap-1" aria-label="Ergebnisse, das jüngste links">
        {games.map((g) => {
          const r = result(g.tore, g.gegentore);
          return (
            <span key={g.id} className={`grid h-6 w-6 place-items-center rounded text-xs font-semibold ${resultClass[r]}`} title={`${g.gegner} ${g.tore}:${g.gegentore}`}>
              {r}
            </span>
          );
        })}
        <span className="ml-2 text-xs text-muted tabular">{pts} Punkte aus {games.length} Spielen</span>
      </div>
      <ul className="divide-y divide-border text-sm">
        {games.map((g) => (
          <li key={g.id} className="flex items-center gap-2 py-1.5 tabular">
            <span className="w-16 shrink-0 text-xs text-muted">{date(g.kickoff)}</span>
            <span className="w-5 shrink-0 text-xs text-muted">{g.ort === "H" ? "vs." : "@"}</span>
            <span className="flex min-w-0 flex-1 flex-col">
              <TeamName name={g.gegner} short link={false} logoSize={16} />
              {g.wettbewerb && <span className="truncate text-[11px] text-muted">{g.wettbewerb}</span>}
            </span>
            {g.xg != null && (
              <span className="shrink-0 text-xs text-muted" title="xG eigene : gegnerische">
                {num(g.xg, 1)}:{num(g.xga, 1)}
              </span>
            )}
            <ResultChip own={g.tore} opp={g.gegentore} />
          </li>
        ))}
      </ul>
    </>
  );
}

function H2HBlock({ d }: { d: MatchDetail }) {
  const s = d.h2h_summary;
  const { home, away } = d.game;
  if (!s.spiele) return <p className="text-sm text-muted">Die beiden Teams haben im erfassten Zeitraum noch nicht gegeneinander gespielt.</p>;
  const parts: [string, number, string][] = [
    [`Siege ${shortName(home)}`, s.siege_heim, "bg-home"],
    ["Remis", s.remis, "bg-draw"],
    [`Siege ${shortName(away)}`, s.siege_gast, "bg-away"],
  ];
  return (
    <Card className="space-y-3">
      <div>
        <div className="flex h-2 overflow-hidden rounded-full">
          {parts.map(([k, v, c]) => (
            <div key={k} className={c} style={{ width: `${(100 * v) / s.spiele}%` }} />
          ))}
        </div>
        <div className="mt-1 flex justify-between gap-2 text-xs text-muted tabular">
          {parts.map(([k, v]) => (
            <span key={k} className="whitespace-nowrap">
              {k} <span className="font-semibold text-foreground">{v}</span>
            </span>
          ))}
        </div>
        <p className="mt-1 text-xs text-muted tabular">
          {s.spiele} Spiele, Tore {s.tore_heim}:{s.tore_gast} aus Sicht von {shortName(home)}
        </p>
      </div>
      <H2HList games={d.h2h.slice(0, 10)} />
      {d.h2h.length > 10 && (
        <details className="group text-xs">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-muted hover:text-foreground [&::-webkit-details-marker]:hidden">
            <span className="inline-block transition-transform group-open:rotate-90">▸</span>
            Alle {d.h2h.length} Duelle zeigen
          </summary>
          <H2HList games={d.h2h.slice(10)} />
        </details>
      )}
    </Card>
  );
}

function H2HList({ games }: { games: DetailH2H[] }) {
  return (
    <ul className="divide-y divide-border text-sm">
      {games.map((g) => (
        <li key={g.id} className="grid grid-cols-[4rem_minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 py-1.5 tabular">
          <span className="flex flex-col text-xs text-muted">
            {date(g.kickoff)}
            <span className="truncate text-[11px]">{g.wettbewerb ?? g.saison}</span>
          </span>
          <TeamName name={g.home} short link={false} logoSize={16} className="justify-self-end" align="end" />
          <span className="flex flex-col items-center">
            <span className="font-semibold">
              {g.home_goals}:{g.away_goals}
            </span>
            {g.home_xg != null && g.away_xg != null && (
              <span className="text-[11px] text-muted">
                xG {num(g.home_xg, 1)}:{num(g.away_xg, 1)}
              </span>
            )}
          </span>
          <TeamName name={g.away} short link={false} logoSize={16} />
        </li>
      ))}
    </ul>
  );
}

function TableBlock({ d }: { d: MatchDetail }) {
  const t = d.tabelle;
  if (!t || (!t.home && !t.away)) return null;
  const rows = [t.home, t.away].filter((r) => r != null);
  const isBl = rows.some((r) => r.xg != null);
  const zones = t.zonen ?? [];
  const zoneKey = (k: string) => k as keyof typeof rows[number];
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm tabular [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Team</th>
            <th className="px-3 py-2 text-right">Sp</th>
            <th className="px-3 py-2 text-right">Tore</th>
            <th className="px-3 py-2 text-right">Pkt</th>
            {isBl && <th className="px-3 py-2 text-right">xG</th>}
            {isBl && <th className="px-3 py-2 text-right">xGA</th>}
            {isBl && <th className="px-3 py-2 text-right">xPts</th>}
            {!isBl && rows.some((r) => r.prognose_platz != null) && <th className="px-3 py-2 text-right">Prognose</th>}
            {!isBl && zones.map((z) => <th key={z.key} className="px-3 py-2 text-right">{z.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-b border-border last:border-0">
              <td className="px-3 py-2">
                {r.platz}
                {r.platz_diff != null && r.platz_diff !== 0 && (
                  <span className={`ml-1 text-xs ${r.platz_diff > 0 ? "text-home" : "text-away"}`}>
                    {r.platz_diff > 0 ? `+${r.platz_diff}` : `−${-r.platz_diff}`}
                  </span>
                )}
              </td>
              <td className="max-w-48 px-3 py-2">
                <TeamName name={r.name} short logoSize={16} link={isBl} />
              </td>
              <td className="px-3 py-2 text-right">{r.sp}</td>
              <td className="px-3 py-2 text-right">
                {r.tore}:{r.gegentore}
              </td>
              <td className="px-3 py-2 text-right font-semibold">{r.pkt}</td>
              {isBl && <td className="px-3 py-2 text-right">{num(r.xg, 1)}</td>}
              {isBl && <td className="px-3 py-2 text-right">{num(r.xga, 1)}</td>}
              {isBl && <td className="px-3 py-2 text-right">{num(r.xpts, 1)}</td>}
              {!isBl && rows.some((x) => x.prognose_platz != null) && <td className="px-3 py-2 text-right">{r.prognose_platz ?? "–"}</td>}
              {!isBl &&
                zones.map((z) => {
                  const v = r[zoneKey(z.key)] as number | undefined;
                  return (
                    <td key={z.key} className="px-3 py-2 text-right">
                      {v == null ? "–" : v < 1 && v > 0 ? "<1 %" : `${Math.round(v)} %`}
                    </td>
                  );
                })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScorerList({ list }: { list: Scorer[] }) {
  if (!list.length) return <p className="text-sm text-muted">Keine Daten.</p>;
  const max = Math.max(...list.map((s) => s.p));
  return (
    <ul className="space-y-1.5 text-sm">
      {list.map((s) => (
        <li key={s.name} className="grid grid-cols-[minmax(0,1fr)_3rem] items-center gap-2 tabular">
          <span className="relative min-w-0">
            <span className="absolute inset-y-0 left-0 rounded bg-home/15" style={{ width: `${(100 * s.p) / max}%` }} />
            <span className="relative block truncate px-1.5">{s.name}</span>
          </span>
          <span className="text-right text-xs text-muted">{Math.round(s.p * 100)} %</span>
        </li>
      ))}
    </ul>
  );
}

const ROW_LABELS = (rows: number[]) =>
  rows.map((r, i) => (i === 0 ? "Tor" : i === rows.length - 1 ? "Angriff" : i === 1 ? "Abwehr" : "Mittelfeld"));

function Lineup({ players }: { players: { reihe: number | null; name: string }[] }) {
  if (!players.length) return <p className="text-sm text-muted">Noch keine Aufstellung von Ligainsider.</p>;
  const rows = [...new Set(players.map((p) => p.reihe ?? 0))].sort((a, b) => a - b);
  const labels = ROW_LABELS(rows);
  return (
    <dl className="space-y-1 text-sm">
      {rows.map((r, i) => (
        <div key={r} className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2">
          <dt className="text-xs leading-5 text-muted">{labels[i]}</dt>
          <dd>
            {players
              .filter((p) => (p.reihe ?? 0) === r)
              .map((p) => lastName(p.name))
              .join(", ")}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function AbsenceBlock({ rows }: { rows: DetailAbsence[] }) {
  if (!rows.length) return <p className="text-sm text-muted">Keine bekannten Ausfälle.</p>;
  return (
    <ul className="divide-y divide-border text-sm">
      {rows.map((a) => (
        <li key={`${a.player_name}-${a.kind}`} className="flex flex-wrap items-baseline justify-between gap-x-2 py-1.5">
          <span>
            <span className="font-medium">{a.player_name}</span>
            {a.stammspieler && <span className="ml-2 rounded bg-away/15 px-1.5 text-xs text-away">Stammspieler</span>}
          </span>
          <span className="text-xs text-muted tabular">
            {a.kind === "suspension" ? "Sperre" : (a.reason ?? "Verletzung")}
            {a.expected_return ? ` · bis ${a.expected_return}` : ""}
            {(a.anteil_xg_xa ?? 0) >= 0.005 ? ` · ${pct(a.anteil_xg_xa)} der xG+xA` : ""}
            {(a.value_share ?? 0) >= 0.005 ? ` · ${pct(a.value_share)} des Kaderwerts` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

const STAT_ROWS: [keyof MatchStats, string, number, boolean][] = [
  // Schlüssel, Beschriftung, Nachkommastellen, weniger = besser
  ["xg", "xG", 2, false],
  ["shots", "Schüsse", 0, false],
  ["shots_on_target", "aufs Tor", 0, false],
  ["big_chances", "Großchancen", 0, false],
  ["corners", "Ecken", 0, false],
  ["ppda", "PPDA", 1, true],
  ["fouls", "Fouls", 0, true],
  ["yellow_cards", "Gelb", 0, true],
  ["red_cards", "Rot", 0, true],
  ["xpts", "xPts", 2, false],
];

function StatsBlock({ s }: { s: { home: MatchStats; away: MatchStats } }) {
  // vor 2000/01 gibt es nur Tore, ohne xG keine PPDA: nur Zeilen mit Werten, sonst gar nichts
  const rows = STAT_ROWS.filter(([k]) => s.home[k] != null && s.away[k] != null);
  if (!rows.length) return null;
  return (
    <Section title="Spielstatistik">
      <Card>
        <ul className="space-y-2 text-sm tabular">
          {rows.map(([k, label, digits, lessIsBetter]) => {
            const h = Number(s.home[k]);
            const a = Number(s.away[k]);
            const total = h + a || 1;
            const better = h === a ? null : (h > a) !== lessIsBetter ? "home" : "away";
            return (
              <li key={k}>
                <div className="flex justify-between text-xs">
                  <span className={better === "home" ? "font-semibold" : "text-muted"}>{num(h, digits)}</span>
                  <span className="text-muted">{label}</span>
                  <span className={better === "away" ? "font-semibold" : "text-muted"}>{num(a, digits)}</span>
                </div>
                <div className="mt-0.5 flex h-1.5 gap-0.5 overflow-hidden rounded-full">
                  <div className="bg-home" style={{ width: `${(100 * h) / total}%` }} />
                  <div className="bg-away" style={{ width: `${(100 * a) / total}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
    </Section>
  );
}

function OddsBlock({ d }: { d: MatchDetail }) {
  const g = d.game;
  const rows = [
    ...(g.p_home != null ? [{ label: "Modell", p: [g.p_home, g.p_draw!, g.p_away!], strong: true }] : []),
    ...(d.quoten ?? []).map((q) => ({
      label: `${q.bookmaker === "Avg" ? "Buchmacher-Schnitt" : "Bet365"} ${q.is_closing ? "(Schluss)" : "(Eröffnung)"}`,
      p: [q.p_home, q.p_draw, q.p_away],
      strong: false,
    })),
  ];
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm tabular [&_td]:whitespace-nowrap">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2" />
            <th className="px-3 py-2 text-right">1</th>
            <th className="px-3 py-2 text-right">X</th>
            <th className="px-3 py-2 text-right">2</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b border-border last:border-0">
              <td className={`px-3 py-2 ${r.strong ? "font-medium" : "text-muted"}`}>{r.label}</td>
              {r.p.map((v, i) => (
                <td key={i} className="px-3 py-2 text-right">
                  {pct(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Kopf: Teams, Ergebnis oder Anstoß, Prognose mit Tipp, TV-Sender. */
function Header({ d, meta }: { d: MatchDetail; meta: string }) {
  const g = d.game;
  const hasPrediction = g.p_home != null && g.p_draw != null && g.p_away != null;
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span>{meta}</span>
        <span>{kickoff(g.kickoff)}</span>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 text-base font-semibold sm:text-lg">
        <span className="min-w-0">
          {/* auf dem Handy Kurzname, sonst wird der volle Name abgeschnitten */}
          <TeamName name={g.home} short logoSize={32} className="sm:hidden" />
          <TeamName name={g.home} logoSize={36} className="max-sm:hidden" />
        </span>
        <div className="flex flex-col items-center whitespace-nowrap tabular">
          <span className={g.finished ? "text-2xl font-bold" : "text-xl text-muted"}>
            {g.finished ? `${g.home_goals}:${g.away_goals}` : "–:–"}
          </span>
          {g.finished && g.home_xg != null && g.away_xg != null && (
            <span className="text-xs font-normal text-muted">
              xG {num(g.home_xg, 1)}:{num(g.away_xg, 1)}
            </span>
          )}
        </div>
        <span className="min-w-0 justify-self-end text-right">
          <TeamName name={g.away} short logoSize={32} align="end" className="sm:hidden" />
          <TeamName name={g.away} logoSize={36} align="end" className="max-sm:hidden" />
        </span>
      </div>
      {hasPrediction ? (
        <div className="space-y-2">
          <ProbabilityBar home={g.p_home!} draw={g.p_draw!} away={g.p_away!} />
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-xs text-muted tabular">
            <span>
              Erw. Tore {num(g.exp_home_goals, 1)} : {num(g.exp_away_goals, 1)}
              {g.basis && <> · {g.basis === "live" ? "Live-Prognose" : "Rückblick-Prognose"}</>}
            </span>
            {g.tip_home != null && (
              <span>
                Tipp{" "}
                <span className="text-base font-semibold text-foreground">
                  {g.tip_home}:{g.tip_away}
                </span>
                {g.points != null && <span className="ml-2">{g.points} P.</span>}
              </span>
            )}
          </div>
          {(g.elo_home != null || d.kaderwert) && (
            <p className="text-xs text-muted tabular">
              {g.elo_home != null && (
                <>
                  Elo {num(g.elo_home, 0)} : {num(g.elo_away, 0)}
                </>
              )}
              {d.kaderwert && (d.kaderwert.home != null || d.kaderwert.away != null) && (
                <>
                  {g.elo_home != null && " · "}Kaderwert {mio(d.kaderwert.home)} : {mio(d.kaderwert.away)}
                </>
              )}
            </p>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted">
          {g.season < 2014 ? "Prognosen gibt es ab 2014/15, ältere Saisons sind nur zum Nachschlagen da." : "Keine Prognose für dieses Spiel."}
        </p>
      )}
      <VenueLine ort={g.ort} className="text-sm" />
      {!g.finished && <TvLine tv={g.tv} />}
    </Card>
  );
}

export function MatchDetailView({
  d,
  meta,
  backHref,
  backLabel,
  rounds = [],
}: {
  d: MatchDetail;
  meta: string;
  backHref: string;
  backLabel: string;
  rounds?: TipRound[];
}) {
  const g = d.game;
  const tip = g.tip_home != null ? `${g.tip_home}:${g.tip_away}` : null;
  const euro = d.form.home.some((x) => x.wettbewerb) || d.form.away.some((x) => x.wettbewerb);
  return (
    <div className="space-y-6">
      <Link href={backHref} className="text-sm text-muted underline hover:text-foreground">
        ← {backLabel}
      </Link>
      <Header d={d} meta={meta} />
      <TipRoundSelect rounds={rounds} current={d.tipprunde?.slug} />

      {tip && g.explanation.length > 0 && (
        <Section title={`Warum ${tip}?`}>
          <Card>
            <ul className="list-disc space-y-1 pl-4 text-sm text-muted">
              {g.explanation.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </Card>
        </Section>
      )}

      <Section title={`Form vor dem Spiel${euro ? " (alle Wettbewerbe)" : ""}`}>
        <Sides home={g.home} away={g.away} data={d.form} render={(games) => <FormList games={games} />} />
      </Section>

      <Section title="Direktvergleich vor dem Spiel">
        <H2HBlock d={d} />
      </Section>

      {d.tabelle && (d.tabelle.home || d.tabelle.away) && (
        <Section title={`Tabelle ${d.tabelle.stand}${g.finished ? "" : ", aktueller Stand"}`}>
          <TableBlock d={d} />
        </Section>
      )}

      {g.torschuetzen && (g.torschuetzen.home.length > 0 || g.torschuetzen.away.length > 0) && (
        <Section title="Wer trifft?">
          <Sides home={g.home} away={g.away} data={g.torschuetzen} render={(list) => <ScorerList list={list} />} />
          <p className="mt-2 text-xs text-muted">Chance auf mindestens ein Tor, aus xG, Einsatzchance und Torerwartung des Teams.</p>
        </Section>
      )}

      {d.aufstellung && (
        <Section title="Voraussichtliche Aufstellung">
          <Sides home={g.home} away={g.away} data={d.aufstellung} render={(p) => <Lineup players={p} />} />
          <p className="mt-2 text-xs text-muted">Laut Ligainsider, letzter Abruf. Kann sich bis zum Anpfiff noch ändern.</p>
        </Section>
      )}

      {d.ausfaelle && (
        <Section title="Ausfälle">
          <Sides home={g.home} away={g.away} data={d.ausfaelle} render={(rows) => <AbsenceBlock rows={rows} />} />
        </Section>
      )}

      {d.statistik && <StatsBlock s={d.statistik} />}

      {d.quoten && d.quoten.length > 0 && (
        <Section title="Modell und Wettmarkt">
          <OddsBlock d={d} />
          <p className="mt-2 text-xs text-muted">Quoten ohne Buchmacher-Marge in Wahrscheinlichkeiten umgerechnet.</p>
        </Section>
      )}

      <Legend
        items={[
          ["S · U · N", "Sieg, Unentschieden, Niederlage aus Sicht des Teams; das jüngste Spiel steht links"],
          ["xG", "Expected Goals: wie viele Tore die Torchancen im Schnitt wert waren, eigene : gegnerische (links mehr = besser)"],
          ["Erw. Tore", "Torerwartung des Modells für Heim : Gast"],
          ["Tipp", "Ergebnis mit den meisten erwarteten Punkten nach der Punkteregel der Tipprunde"],
          ...(d.tabelle?.zonen ? [] : [TERMS.xpts]),
          ...(d.tabelle?.home?.platz_diff != null ? [TERMS.platz] : []),
          ...(d.statistik ? [TERMS.ppda] : []),
          ...(g.elo_home != null ? [["Elo", "Spielstärke-Wert aus allen Liga- und Europapokalspielen (mehr = besser)"] as [string, string]] : []),
        ]}
      />
    </div>
  );
}
