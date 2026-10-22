import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { getKickbaseLineup, getKickbaseProjections, load } from "@/lib/api";
import { KickbaseLineup } from "./KickbaseLineup";
import { KickbaseTable } from "./KickbaseTable";

async function Content({ searchParams }: { searchParams: PageProps<"/kickbase">["searchParams"] }) {
  const sp = await searchParams;
  const matchdays = Math.min(Math.max(Number(sp.spieltage) || 1, 1), 5);
  const res = await load(() => Promise.all([getKickbaseProjections(matchdays), getKickbaseLineup()]));
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [rows, lineup] = res.data;
  return (
    <div className="space-y-4">
      <KickbaseLineup l={lineup} />
      <KickbaseTable rows={rows} matchdays={matchdays} />
    </div>
  );
}

export default function Page(props: PageProps<"/kickbase">) {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="whitespace-nowrap text-xl font-semibold">Kickbase</h1>
        <p className="text-sm text-muted">
          Erwartete Einsätze, Tore, Vorlagen und Zu-null-Chancen je Spieler für die nächsten Spieltage, aus xG/xA,
          Startelf-Quote, Ausfällen und der Prognose für jedes Spiel.
        </p>
      </div>
      <Suspense fallback={<p className="text-muted">Berechne Projektion …</p>}>
        <Content searchParams={props.searchParams} />
      </Suspense>
    </div>
  );
}
