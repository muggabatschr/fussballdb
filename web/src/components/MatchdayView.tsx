import type { Bilanz, Matchday, MatchdayGame, Punkteregel, Season } from "@/lib/api";
import { kickoff, num } from "@/lib/format";
import { Card } from "./Card";
import { MatchdayNav } from "./MatchdayNav";
import { ProbabilityBar } from "./ProbabilityBar";
import { TeamName } from "./TeamName";
import { WhyTip } from "./WhyTip";

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

function Game({ g, regel }: { g: MatchdayGame; regel: Punkteregel }) {
  const hasPrediction = g.p_home != null && g.p_draw != null && g.p_away != null;
  return (
    <Card className="space-y-3">
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
        <TeamName name={g.home} short />
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
        <TeamName name={g.away} short align="end" className="justify-self-end" />
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
          {g.tip_home != null && <WhyTip tip={`${g.tip_home}:${g.tip_away}`} lines={g.explanation} />}
        </>
      ) : (
        <p className="text-xs text-muted">Keine Prognose (vor diesem Spieltag gab es noch keine Daten).</p>
      )}
    </Card>
  );
}

function BilanzText({ label, b }: { label: string; b: Bilanz }) {
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

export function MatchdayView({ seasons, data }: { seasons: Season[]; data: Matchday }) {
  const label = seasons.find((s) => s.start_year === data.season)?.label;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="whitespace-nowrap text-xl font-semibold">
          {data.matchday}. Spieltag <span className="text-muted">{label}</span>
        </h1>
        <MatchdayNav seasons={seasons} season={data.season} matchday={data.matchday} />
      </div>
      {data.summary.spiele > 0 && (
        <Card className="grid gap-4 sm:grid-cols-2">
          <BilanzText label="Tipps dieses Spieltags" b={data.summary} />
          <BilanzText label={`Saison ${label} bis hier`} b={data.season_summary} />
          <p className="text-xs text-muted sm:col-span-2">
            Punkteregel der Tipprunde: Sieg {data.punkteregel.sieg_tendenz} Tendenz, {data.punkteregel.sieg_tordifferenz}{" "}
            Tordifferenz, {data.punkteregel.exakt} exakt · Remis {data.punkteregel.remis_tendenz} Tendenz,{" "}
            {data.punkteregel.exakt} exakt. Der Tipp ist das Ergebnis mit den meisten erwarteten Punkten nach dieser Regel.
            Rückblick-Prognosen nutzen nur Daten bis zum ersten Anpfiff des Spieltags, als Ausfälle die damals gemeldeten
            Verletzten (ab 2023/24).
          </p>
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {data.games.map((g) => (
          <Game key={g.id} g={g} regel={data.punkteregel} />
        ))}
      </div>
    </div>
  );
}
