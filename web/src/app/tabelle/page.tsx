import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { LeagueTable } from "@/components/LeagueTable";
import { getTable, load } from "@/lib/api";

async function Table() {
  const res = await load(() => getTable());
  return res.ok ? <LeagueTable rows={res.data} /> : <ErrorBox message={res.error} />;
}

export default function Page() {
  return (
    <>
      <h1 className="mb-1 text-xl font-semibold">Tabelle</h1>
      <p className="mb-4 text-sm text-muted">
        Mit xG und erwarteten Punkten (xPts). Positive Werte bei „Pkt − xPts“ bedeuten mehr Punkte als die Chancen
        hergeben.
      </p>
      <Suspense fallback={<p className="text-muted">Lade Tabelle …</p>}>
        <Table />
      </Suspense>
    </>
  );
}
