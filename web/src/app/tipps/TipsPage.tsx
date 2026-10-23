import { ErrorBox } from "@/components/Card";
import { TipRoundSelect } from "@/components/TipRoundSelect";
import { TipSheet } from "@/components/TipSheet";
import { getMatchday, getSeasons, getTipRounds, load } from "@/lib/api";
import { selectedTipRound } from "@/lib/tipround";

/** Tipp-Zettel eines Spieltags nach der Punkteregel der gewählten Tipprunde; ohne Angabe der aktuelle Spieltag
 * der neuesten Saison. */
export async function TipsPage({ season, matchday }: { season?: number; matchday?: number }) {
  const runde = await selectedTipRound();
  const res = await load(async () => {
    const seasons = await getSeasons();
    const s = seasons.find((x) => x.start_year === season) ?? seasons[0];
    return [s, await getMatchday(s.start_year, matchday ?? s.current_matchday, runde), await getTipRounds()] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [s, data, rounds] = res.data;
  const round = rounds.length > 1 && data.tipprunde?.name ? ` · ${data.tipprunde.name}` : "";
  return (
    <div className="space-y-3">
      <TipSheet
        title={`${data.matchday}. Spieltag`}
        subtitle={`Bundesliga ${s.label}${round}`}
        games={data.games}
        backHref={`/spieltag/${data.season}/${data.matchday}`}
        backLabel="zum Spieltag"
        fileName={`tipps-bundesliga-${data.season}-${data.matchday}${data.tipprunde?.slug ? `-${data.tipprunde.slug}` : ""}.png`}
      />
      <TipRoundSelect rounds={rounds} current={data.tipprunde?.slug} />
    </div>
  );
}
