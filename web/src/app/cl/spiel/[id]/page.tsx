import { Suspense } from "react";
import { CompMatchPage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/cl/spiel/[id]">["params"] }) {
  const { id } = await params;
  return <CompMatchPage comp="CL" id={Number(id)} />;
}

export default function Page(props: PageProps<"/cl/spiel/[id]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Spiel …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
