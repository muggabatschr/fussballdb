import { ErrorBox } from "@/components/Card";
import { TipSheet } from "@/components/TipSheet";
import { getMatchday, getSeasons, load } from "@/lib/api";

/** Tipp-Zettel eines Spieltags; ohne Angabe der aktuelle Spieltag der neuesten Saison. */
export async function TipsPage({ season, matchday }: { season?: number; matchday?: number }) {
  const res = await load(async () => {
    const seasons = await getSeasons();
    const s = seasons.find((x) => x.start_year === season) ?? seasons[0];
    return [s, await getMatchday(s.start_year, matchday ?? s.current_matchday)] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [s, data] = res.data;
  return (
    <TipSheet
      title={`${data.matchday}. Spieltag`}
      subtitle={`Bundesliga ${s.label}`}
      games={data.games}
      backHref={`/spieltag/${data.season}/${data.matchday}`}
      backLabel="zum Spieltag"
      fileName={`tipps-bundesliga-${data.season}-${data.matchday}.png`}
    />
  );
}
