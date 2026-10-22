import { Suspense } from "react";
import { TipsPage } from "../../TipsPage";

async function Content({ params }: { params: PageProps<"/tipps/[saison]/[nr]">["params"] }) {
  const { saison, nr } = await params;
  return <TipsPage season={Number(saison)} matchday={Number(nr)} />;
}

export default function Page(props: PageProps<"/tipps/[saison]/[nr]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tipps …</p>}>
      <Content params={props.params} />
    </Suspense>
  );
}
