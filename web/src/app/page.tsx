import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { MatchdayView } from "@/components/MatchdayView";
import { getMatchday, getSeasons, getTipRounds, load } from "@/lib/api";
import { selectedTipRound } from "@/lib/tipround";

// Startseite: aktueller Spieltag der neuesten Saison
async function Current() {
  const res = await load(async () => {
    const seasons = await getSeasons();
    const latest = seasons[0];
    const runde = await selectedTipRound();
    return [seasons, await getMatchday(latest.start_year, latest.current_matchday, runde), await getTipRounds()] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data, rounds] = res.data;
  return <MatchdayView seasons={seasons} data={data} rounds={rounds} />;
}

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spieltag …</p>}>
      <Current />
    </Suspense>
  );
}
