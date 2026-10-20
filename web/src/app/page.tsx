import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { MatchdayView } from "@/components/MatchdayView";
import { getMatchday, getSeasons, load } from "@/lib/api";

// Startseite: aktueller Spieltag der neuesten Saison
async function Current() {
  const res = await load(async () => {
    const seasons = await getSeasons();
    const latest = seasons[0];
    return [seasons, await getMatchday(latest.start_year, latest.current_matchday)] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data] = res.data;
  return <MatchdayView seasons={seasons} data={data} />;
}

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spieltag …</p>}>
      <Current />
    </Suspense>
  );
}
