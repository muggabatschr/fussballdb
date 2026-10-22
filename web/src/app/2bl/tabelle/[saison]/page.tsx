import { Suspense } from "react";
import { CompTablePage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/2bl/tabelle/[saison]">["params"] }) {
  const { saison } = await params;
  return <CompTablePage comp="D2" season={Number(saison)} />;
}

export default function Page(props: PageProps<"/2bl/tabelle/[saison]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tabelle …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
