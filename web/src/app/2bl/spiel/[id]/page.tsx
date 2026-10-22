import { Suspense } from "react";
import { CompMatchPage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/2bl/spiel/[id]">["params"] }) {
  const { id } = await params;
  return <CompMatchPage comp="D2" id={Number(id)} />;
}

export default function Page(props: PageProps<"/2bl/spiel/[id]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spiel …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
