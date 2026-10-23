import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { MatchdayView } from "@/components/MatchdayView";
import { getMatchday, getSeasons, getTipRounds, load } from "@/lib/api";
import { selectedTipRound } from "@/lib/tipround";

async function Content({ params }: { params: PageProps<"/spieltag/[saison]/[nr]">["params"] }) {
  const { saison, nr } = await params;
  const runde = await selectedTipRound();
  const res = await load(() => Promise.all([getSeasons(), getMatchday(Number(saison), Number(nr), runde), getTipRounds()]));
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data, rounds] = res.data;
  return <MatchdayView seasons={seasons} data={data} rounds={rounds} />;
}

export default function Page(props: PageProps<"/spieltag/[saison]/[nr]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spieltag …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
