import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { MatchDetailView } from "@/components/MatchDetail";
import { getMatchDetail, load } from "@/lib/api";

async function Content({ params }: { params: PageProps<"/spiel/[id]">["params"] }) {
  const { id } = await params;
  const res = await load(() => getMatchDetail(Number(id)));
  if (!res.ok) return <ErrorBox message={res.error} />;
  const d = res.data;
  const g = d.game;
  return (
    <MatchDetailView
      d={d}
      meta={`Bundesliga · ${g.matchday}. Spieltag · ${g.season_label}`}
      backHref={`/spieltag/${g.season}/${g.matchday}`}
      backLabel={`zum ${g.matchday}. Spieltag`}
    />
  );
}

export default function Page(props: PageProps<"/spiel/[id]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spiel …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
