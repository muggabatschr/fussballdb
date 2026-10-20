import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { ClView } from "@/components/ClView";
import { getClRound, getClRounds, load } from "@/lib/api";

async function Content({ params }: { params: PageProps<"/cl/[saison]/[runde]">["params"] }) {
  const { saison, runde } = await params;
  const res = await load(() => Promise.all([getClRounds(), getClRound(Number(saison), Number(runde))]));
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data] = res.data;
  return <ClView seasons={seasons} data={data} />;
}

export default function Page(props: PageProps<"/cl/[saison]/[runde]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Runde …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
