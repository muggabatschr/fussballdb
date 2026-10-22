import { Suspense } from "react";
import { CompTipsPage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/pokal/tipps/[saison]/[runde]">["params"] }) {
  const { saison, runde } = await params;
  return <CompTipsPage comp="DFB" season={Number(saison)} round={Number(runde)} />;
}

export default function Page(props: PageProps<"/pokal/tipps/[saison]/[runde]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tipps …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
