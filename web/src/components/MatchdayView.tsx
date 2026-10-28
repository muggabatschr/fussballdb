import type { Bilanz, Matchday, MatchdayGame, Punkteregel, Scorer, Season, TipRound } from "@/lib/api";
import Image from "next/image";
import Link from "next/link";
import { kickoff, num } from "@/lib/format";
import { shortName } from "@/lib/teams";
import { tvLogo } from "@/lib/tv";
import { Card } from "./Card";
import { CompetitionTabs } from "./CompetitionTabs";
import { MatchdayNav } from "./MatchdayNav";
import { AdvanceLine } from "./AdvanceLine";
import { ProbabilityBar } from "./ProbabilityBar";
import { TeamName } from "./TeamName";
import { TipRoundSelect } from "./TipRoundSelect";
import { VenueLine } from "./VenueLine";
import { WhyTip } from "./WhyTip";
import { Legend, TILE_LEGEND } from "./Legend";

function pointsLabel(g: MatchdayGame, r: Punkteregel): string {
  if (g.points === r.exakt) return "exakt";
  if (!g.points) return "daneben";
  if (g.home_goals === g.away_goals) return "Remis richtig";
  return g.points === r.sieg_tordifferenz ? "Tordifferenz" : "Tendenz";
}

function pointsClass(points: number, r: Punkteregel): string {
  if (points === r.exakt) return "bg-home text-white dark:text-black";
  if (points === 0) return "bg-away/20 text-away";
  return points >= r.sieg_tordifferenz ? "bg-home/70 text-white dark:text-black" : "bg-home/30";
}

// kurz, damit die Zeile auch auf dem Handy nicht umbricht: "19.10.26, 11:39"
const stand = (iso: string) =>
  new Date(iso).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Berlin",
  });

/** Tore minus xG eines Teams: grün = mehr Tore als die Chancen hergaben (überperformt),
 * orange = weniger (unterperformt), grau = Abweichung unter einem halben Tor. */
function XgDelta({ goals, xg, className = "" }: { goals: number; xg: number; className?: string }) {
  const d = goals - xg;
  const color = d >= 0.5 ? "text-home" : d <= -0.5 ? "text-away" : "text-muted";
  const label = d >= 0.5 ? "überperformt" : d <= -0.5 ? "unterperformt" : "im Rahmen";
  return (
    <span
      className={`whitespace-nowrap text-xs font-normal tabular ${color} ${className}`}
      title={`${goals} ${goals === 1 ? "Tor" : "Tore"} bei ${num(xg, 1)} xG: ${label}`}
    >
      {d > 0 ? "+" : d < 0 ? "−" : "±"}
      {num(Math.abs(d), 1)} ggü. xG
    </span>
  );
}

/** Kachel eines Spiels. Mit `href` ist die ganze Kachel ein Link zur Detailseite; Teamnamen, „Warum?“ und
 * „Wer trifft?“ liegen darüber und bleiben einzeln klickbar. */
export function Game({ g, regel, href }: { g: MatchdayGame; regel: Punkteregel; href?: string }) {
  const hasPrediction = g.p_home != null && g.p_draw != null && g.p_away != null;
  return (
    <Card className={`relative space-y-3 ${href ? "transition-colors hover:border-foreground/30" : ""}`}>
      {href && (
        <Link href={href} className="absolute inset-0 rounded-lg" aria-label={`Details zu ${g.home} gegen ${g.away}`} />
      )}
      <div className="flex items-center justify-between gap-2 whitespace-nowrap text-xs text-muted">
        <span className="truncate">{kickoff(g.kickoff)}</span>
        <span className="flex shrink-0 items-center gap-2 tabular">
          {g.tip_home != null && (
            <span>
              Tipp{" "}
              <span className="text-sm font-semibold text-foreground">
                {g.tip_home}:{g.tip_away}
              </span>
            </span>
          )}
          {g.points != null && (
            <span className={`rounded px-1.5 py-0.5 ${pointsClass(g.points, regel)}`} title={pointsLabel(g, regel)}>
              {g.points} P.
            </span>
          )}
        </span>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 font-medium">
        <TeamName name={g.home} short className="relative" />
        <div className="flex flex-col items-center whitespace-nowrap tabular">
          <span className={g.finished ? "text-lg font-semibold" : "text-muted"}>
            {g.finished ? `${g.home_goals}:${g.away_goals}` : "–:–"}
          </span>
          {g.finished && g.home_xg != null && (
            <span className="text-xs font-normal text-muted">
              xG {num(g.home_xg, 1)}:{num(g.away_xg, 1)}
            </span>
          )}
        </div>
        <TeamName name={g.away} short align="end" className="relative justify-self-end" />
        {g.finished && g.home_xg != null && g.away_xg != null && (
          <>
            <XgDelta goals={g.home_goals!} xg={g.home_xg} />
            <span />
            <XgDelta goals={g.away_goals!} xg={g.away_xg} className="justify-self-end" />
          </>
        )}
      </div>

      {hasPrediction ? (
        <>
          <ProbabilityBar home={g.p_home!} draw={g.p_draw!} away={g.p_away!} />
          <p className="truncate whitespace-nowrap text-xs text-muted tabular">
            Erw. Tore {num(g.exp_home_goals, 1)} : {num(g.exp_away_goals, 1)}
            {g.as_of && (
              <span title={g.basis === "live" ? "Live-Prognose mit heutigem Datenstand" : "Rückblick: nur Daten bis zum ersten Anpfiff des Spieltags"}>
                {" · "}
                {g.basis === "live" ? "Live" : "Rückblick"} {stand(g.as_of)}
              </span>
            )}
          </p>
          <AdvanceLine g={g} />
          <div className="relative space-y-3 empty:hidden">
            {g.tip_home != null && <WhyTip tip={`${g.tip_home}:${g.tip_away}`} lines={g.explanation} />}
            {!g.finished && <Scorers s={g.torschuetzen} home={g.home} away={g.away} />}
          </div>
          <VenueLine ort={g.ort} />
          {!g.finished && <TvLine tv={g.tv} />}
        </>
      ) : (
        <p className="text-xs text-muted">
          {(g.season ?? 2014) < 2014
            ? "Prognosen gibt es ab 2014/15, ältere Saisons sind nur zum Nachschlagen da."
            : "Keine Prognose (vor diesem Spieltag gab es noch keine Daten)."}
        </p>
      )}
      {href && <p className="text-right text-xs text-muted">Form, Direktvergleich, Ausfälle ›</p>}
    </Card>
  );
}

/** Ein Sender als Logo (Sky-Logos auf weißem Schild, damit sie auch im Dunkelmodus lesbar sind), sonst Text.
 * `suffixes`: Kanalnummern, wenn mehrere Kanäle dasselbe Logo haben (Sky Sport Austria 1, 4). */
function TvChannel({ name, suffixes }: { name: string; suffixes?: string[] }) {
  const l = tvLogo(name);
  if (!l) return <span className="rounded border border-border px-1 leading-4">{name}</span>;
  const h = l.pill ? 16 : 22; // Sky und Prime ohne Rand, mit Schild; DAZN und WOW bringen ihre Fläche mit
  const suffix = (suffixes ?? [l.suffix]).filter(Boolean).join(", ");
  return (
    <span className={`inline-flex h-[22px] shrink-0 items-center gap-1 rounded ${l.pill ? "bg-white px-1.5" : ""}`} title={name}>
      <Image src={l.src} alt={name} width={Math.round((h * l.w) / l.h)} height={h} unoptimized loading="eager" style={{ height: h, width: "auto" }} />
      {suffix && <span className="text-xs font-bold leading-none text-black">{suffix}</span>}
    </span>
  );
}

/** Kanäle mit demselben Logo zusammenfassen: [Sky Sport Austria 1, Sky Sport Austria 4] -> ein Logo mit "1, 4". */
function groupChannels(names: string[]): { name: string; suffixes?: string[] }[] {
  const out: { name: string; src?: string; suffixes?: string[] }[] = [];
  for (const name of names) {
    const l = tvLogo(name);
    const prev = out.find((o) => l?.suffix && o.src === l.src);
    if (prev && l?.suffix) prev.suffixes!.push(l.suffix);
    else if (l && !l.suffix && out.some((o) => o.src === l.src)) continue; // ZDF und ZDF Livestream: ein Logo
    else out.push({ name, src: l?.src, suffixes: l?.suffix ? [l.suffix] : undefined });
  }
  return out;
}

// Nachname ohne Vorname: "Kevin De Bruyne" -> "De Bruyne", "Rodrygo" bleibt
export const lastName = (n: string) => n.split(" ").slice(1).join(" ") || n;

/** Wahrscheinlichste Torschützen je Team (Chance auf mindestens ein Tor), aufklappbar wie die Begründung. */
function Scorers({ s, home, away }: { s?: MatchdayGame["torschuetzen"]; home: string; away: string }) {
  if (!s || (!s.home.length && !s.away.length)) return null;
  const line = (list: Scorer[]) => list.map((x) => `${lastName(x.name)} ${Math.round(x.p * 100)} %`).join(", ");
  return (
    <details className="group text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-1 whitespace-nowrap text-muted hover:text-foreground [&::-webkit-details-marker]:hidden">
        <span className="inline-block transition-transform group-open:rotate-90">▸</span>
        Wer trifft?
      </summary>
      <ul className="mt-1.5 space-y-1 border-l border-border pl-3 text-muted">
        {s.home.length > 0 && (
          <li>
            <span className="text-foreground/80">{shortName(home)}:</span> {line(s.home)}
          </li>
        )}
        {s.away.length > 0 && (
          <li>
            <span className="text-foreground/80">{shortName(away)}:</span> {line(s.away)}
          </li>
        )}
        <li className="text-[11px]">Chance auf mindestens ein Tor, aus xG, Einsatzchance und Torerwartung des Teams.</li>
      </ul>
    </details>
  );
}

// gleiche Darstellung = gleicher Sender (Sky Bundesliga 1 in DE und Sky Sport Bundesliga 1 in AT)
const channelKey = (name: string) => {
  const l = tvLogo(name);
  return l ? `${l.src}#${l.suffix ?? ""}` : name;
};

/** TV-Kanäle in Deutschland und Österreich (FotMob-TV-Programm, etwa eine Woche vor dem Spiel bekannt).
 * Laufen in beiden Ländern dieselben Sender, steht nur eine Zeile "DE/AT" da. */
export function TvLine({ tv }: { tv?: MatchdayGame["tv"] }) {
  const de = tv?.DE ?? [];
  const at = tv?.AT ?? [];
  const same = de.length > 0 && de.map(channelKey).join("|") === at.map(channelKey).join("|");
  const rows: [string, string[]][] = same
    ? [["DE/AT", de]]
    : ([["DE", de], ["AT", at]] as [string, string[]][]).filter(([, names]) => names.length);
  if (!rows.length) return null;
  return (
    <div className="space-y-1 text-xs text-muted">
      {rows.map(([label, names]) => (
        <div key={label} className="flex items-start gap-1.5" title={`TV ${label}: ${names.join(", ")}`}>
          <span className="w-10 shrink-0 pt-[3px] font-medium text-foreground/80">{label}</span>
          {/* viele Sender (Pokal: Sky, RTL+, OneFootball, WOW): in die nächste Zeile umbrechen statt abschneiden */}
          <span className="flex min-w-0 flex-wrap items-center gap-1.5 whitespace-nowrap">
            {groupChannels(names).map((c) => (
              <TvChannel key={c.name} name={c.name} suffixes={c.suffixes} />
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}

export function BilanzText({ label, b }: { label: string; b: Bilanz }) {
  if (!b.spiele) return null;
  const stats: [string, string][] = [
    ["Punkte", String(b.punkte)],
    ["Tendenz", `${b.tendenz}/${b.spiele}`],
    ["exakt", String(b.exakt)],
    ["je Spiel", num(b.punkte / b.spiele, 2)],
  ];
  return (
    <div className="min-w-0">
      <div className="truncate whitespace-nowrap text-xs text-muted">{label}</div>
      <dl className="mt-1 grid grid-cols-4 gap-3 tabular">
        {stats.map(([k, v]) => (
          <div key={k} className="flex flex-col-reverse whitespace-nowrap">
            <dt className="text-xs text-muted">{k}</dt>
            <dd className="text-lg font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function MatchdayView({ seasons, data, rounds = [] }: { seasons: Season[]; data: Matchday; rounds?: TipRound[] }) {
  const label = seasons.find((s) => s.start_year === data.season)?.label;
  return (
    <div className="space-y-4">
      <CompetitionTabs active="BL" />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="whitespace-nowrap text-xl font-semibold">
          {data.matchday}. Spieltag <span className="text-muted">{label}</span>
        </h1>
        <MatchdayNav seasons={seasons} season={data.season} matchday={data.matchday} />
      </div>
      <TipRoundSelect rounds={rounds} current={data.tipprunde?.slug} />
      {data.summary.spiele > 0 && (
        <Card className="grid gap-4 sm:grid-cols-2">
          <BilanzText label="Tipps dieses Spieltags" b={data.summary} />
          <BilanzText label={`Saison ${label} bis hier`} b={data.season_summary} />
          <p className="text-xs text-muted sm:col-span-2">
            Punkteregel der Tipprunde{data.tipprunde?.name ? ` ${data.tipprunde.name}` : ""}: Sieg {data.punkteregel.sieg_tendenz} Tendenz, {data.punkteregel.sieg_tordifferenz}{" "}
            Tordifferenz, {data.punkteregel.exakt} exakt · Remis {data.punkteregel.remis_tendenz} Tendenz,{" "}
            {data.punkteregel.exakt} exakt. Der Tipp ist das Ergebnis mit den meisten erwarteten Punkten nach dieser Regel.
            Rückblick-Prognosen nutzen nur Daten bis zum ersten Anpfiff des Spieltags, als Ausfälle die damals gemeldeten
            Verletzten (ab 2023/24).
          </p>
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {data.games.map((g) => (
          <Game key={g.id} g={g} regel={data.punkteregel} href={`/spiel/${g.id}`} />
        ))}
      </div>
      <Legend items={TILE_LEGEND} />
    </div>
  );
}
