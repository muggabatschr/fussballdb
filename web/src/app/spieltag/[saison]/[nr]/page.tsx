import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { MatchdayView } from "@/components/MatchdayView";
import { getMatchday, getSeasons, load } from "@/lib/api";

async function Content({ params }: { params: PageProps<"/spieltag/[saison]/[nr]">["params"] }) {
  const { saison, nr } = await params;
  const res = await load(() => Promise.all([getSeasons(), getMatchday(Number(saison), Number(nr))]));
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data] = res.data;
  return <MatchdayView seasons={seasons} data={data} />;
}

export default function Page(props: PageProps<"/spieltag/[saison]/[nr]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spieltag …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
