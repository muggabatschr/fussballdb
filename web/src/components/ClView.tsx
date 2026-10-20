import type { ClRound, ClSeason } from "@/lib/api";
import { Card } from "./Card";
import { ClNav } from "./ClNav";
import { BilanzText, Game } from "./MatchdayView";

/** Eine Runde der Champions League: Spiele mit Prognose, Tipp und Punkten wie beim Bundesliga-Spieltag. */
export function ClView({ seasons, data }: { seasons: ClSeason[]; data: ClRound }) {
  const label = seasons.find((s) => s.season === data.season)?.label;
  const r = data.punkteregel;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="whitespace-nowrap text-xl font-semibold">
          {data.round_name} <span className="text-muted">CL {label}</span>
        </h1>
        <ClNav seasons={seasons} season={data.season} round={data.round_no} />
      </div>
      {data.summary.spiele > 0 && (
        <Card className="grid gap-4 sm:grid-cols-2">
          <BilanzText label="Tipps dieser Runde" b={data.summary} />
          <BilanzText label={`Saison ${label} bis hier`} b={data.season_summary} />
          <p className="text-xs text-muted sm:col-span-2">
            Punkteregel wie in der Bundesliga: Sieg {r.sieg_tendenz} Tendenz, {r.sieg_tordifferenz} Tordifferenz,{" "}
            {r.exakt} exakt · Remis {r.remis_tendenz} Tendenz, {r.exakt} exakt. Grundlage ist eine europaweite Elo aus
            Liga- und Europapokalspielen mit dem Kaderwert als Startwert. Rückblick-Prognosen nutzen nur Spiele und
            Kaderwerte bis zum ersten Anpfiff der Runde. Bei K.-o.-Spielen zählt das Endergebnis inklusive Verlängerung.
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
