import { Suspense } from "react";
import { CompRoundPage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/2bl/[saison]/[runde]">["params"] }) {
  const { saison, runde } = await params;
  return <CompRoundPage comp="D2" season={Number(saison)} round={Number(runde)} />;
}

export default function Page(props: PageProps<"/2bl/[saison]/[runde]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Runde …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
