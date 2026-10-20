import { Suspense } from "react";
import { ClTablePage } from "../ClTablePage";

async function Content({ params }: { params: PageProps<"/cl/tabelle/[saison]">["params"] }) {
  const { saison } = await params;
  return <ClTablePage season={Number(saison)} />;
}

export default function Page(props: PageProps<"/cl/tabelle/[saison]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tabelle …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
