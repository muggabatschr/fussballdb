import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { LeagueTable, ProjectionTable } from "@/components/LeagueTable";
import { getTable, load } from "@/lib/api";
import { Legend, TERMS } from "@/components/Legend";

async function Table() {
  const res = await load(() => getTable());
  if (!res.ok) return <ErrorBox message={res.error} />;
  const projected = res.data.some((r) => r.prognose_platz != null);
  return (
    <>
      <LeagueTable rows={res.data} />
      <Legend items={[TERMS.sp, TERMS.tore, TERMS.pkt, TERMS.xg, TERMS.xga, TERMS.xpts, TERMS.diff, TERMS.platz]} />
      {projected && (
        <section className="mt-8">
          <h2 className="mb-1 text-lg font-semibold">Geschätzte Abschlusstabelle</h2>
          <p className="mb-4 text-sm text-muted">
            Alle offenen Spiele 10.000-mal mit den Wahrscheinlichkeiten des Modells durchgespielt. Passt sich nach
            jedem Spieltag an, sobald Ergebnisse und xG da sind.
          </p>
          <ProjectionTable rows={res.data} />
          <Legend
            items={[
              TERMS.erwPkt,
              TERMS.heute,
              ["Meister", "Chance auf Platz 1 in Prozent"],
              ["Top 4", "Chance auf Platz 1–4 (Champions League) in Prozent"],
              ["Abstieg", "Chance auf Platz 17–18 in Prozent (weniger = besser)"],
            ]}
          />
        </section>
      )}
    </>
  );
}

export default function Page() {
  return (
    <>
      <h1 className="mb-1 text-xl font-semibold">Tabelle</h1>
      <p className="mb-4 text-sm text-muted">
        Mit xG und erwarteten Punkten (xPts). Positive Werte bei „Pkt − xPts“ bedeuten mehr Punkte als die Chancen
        hergeben. Die kleine Zahl neben dem Platz zeigt, wie viele Plätze ein Team besser (+) oder schlechter (−)
        steht, als es die Prognosen vor den bisherigen Spielen erwarten ließen.
      </p>
      <Suspense fallback={<p className="text-muted">Lade Tabelle …</p>}>
        <Table />
      </Suspense>
    </>
  );
}
