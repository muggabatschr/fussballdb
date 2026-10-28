import { Suspense } from "react";
import { CompMatchPage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/brasilien/spiel/[id]">["params"] }) {
  const { id } = await params;
  return <CompMatchPage comp="BRA" id={Number(id)} />;
}

export default function Page(props: PageProps<"/brasilien/spiel/[id]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spiel …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
