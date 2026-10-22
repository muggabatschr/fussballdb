import { Suspense } from "react";
import { CompMatchPage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/pokal/spiel/[id]">["params"] }) {
  const { id } = await params;
  return <CompMatchPage comp="DFB" id={Number(id)} />;
}

export default function Page(props: PageProps<"/pokal/spiel/[id]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spiel …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
