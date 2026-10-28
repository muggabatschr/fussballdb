import { Suspense } from "react";
import { CompTablePage } from "@/components/CompPages";

async function Content({ params }: { params: PageProps<"/brasilien/tabelle/[saison]">["params"] }) {
  const { saison } = await params;
  return <CompTablePage comp="BRA" season={Number(saison)} />;
}

export default function Page(props: PageProps<"/brasilien/tabelle/[saison]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tabelle …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
