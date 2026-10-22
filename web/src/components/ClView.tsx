import type { ClRound, ClSeason } from "@/lib/api";
import { COMPETITIONS, type CompCode } from "@/lib/competitions";
import { Card } from "./Card";
import { ClNav } from "./ClNav";
import { CompetitionTabs } from "./CompetitionTabs";
import { BilanzText, Game } from "./MatchdayView";
import { Legend, TILE_LEGEND } from "./Legend";

/** Eine Runde (CL, 2. Liga, Pokal): Spiele mit Prognose, Tipp und Punkten wie beim Bundesliga-Spieltag. */
export function ClView({ seasons, data, comp = "CL" }: { seasons: ClSeason[]; data: ClRound; comp?: CompCode }) {
  const label = seasons.find((s) => s.season === data.season)?.label;
  const r = data.punkteregel;
  const c = COMPETITIONS[comp];
  return (
    <div className="space-y-4">
      <CompetitionTabs active={comp} />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="whitespace-nowrap text-xl font-semibold">
          {data.round_name} <span className="text-muted">{c.short} {label}</span>
        </h1>
        <ClNav seasons={seasons} season={data.season} round={data.round_no} comp={comp} />
      </div>
      {data.summary.spiele > 0 && (
        <Card className="grid gap-4 sm:grid-cols-2">
          <BilanzText label="Tipps dieser Runde" b={data.summary} />
          <BilanzText label={`Saison ${label} bis hier`} b={data.season_summary} />
          <p className="text-xs text-muted sm:col-span-2">
            Punkteregel wie in der Bundesliga: Sieg {r.sieg_tendenz} Tendenz, {r.sieg_tordifferenz} Tordifferenz,{" "}
            {r.exakt} exakt · Remis {r.remis_tendenz} Tendenz, {r.exakt} exakt. {c.note} Rückblick-Prognosen nutzen
            nur Spiele und Kaderwerte bis zum ersten Anpfiff der Runde.
          </p>
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {data.games.map((g) => (
          <Game key={g.id} g={g} regel={data.punkteregel} />
        ))}
      </div>
      <Legend items={TILE_LEGEND} />
    </div>
  );
}
