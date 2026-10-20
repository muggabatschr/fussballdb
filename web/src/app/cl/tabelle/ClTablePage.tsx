import Link from "next/link";
import { ErrorBox } from "@/components/Card";
import { ClLeagueTable, ClProjectionTable, ClTableSeasons } from "@/components/ClTable";
import { getClRounds, getClTable, load } from "@/lib/api";

/** Ligaphasen-Tabelle einer CL-Saison (ohne Angabe die neueste) mit Hochrechnung. */
export async function ClTablePage({ season }: { season?: number }) {
  const res = await load(async () => {
    const seasons = await getClRounds();
    const s = season ?? seasons[0].season;
    return [seasons, await getClTable(s)] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data] = res.data;
  const projected = data.rows.some((r) => r.prognose_platz != null);
  const latest = seasons.find((s) => s.season === data.season);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="whitespace-nowrap text-xl font-semibold">
          Ligaphase <span className="text-muted">CL {data.label}</span>
        </h1>
        <ClTableSeasons seasons={seasons} current={data.season} />
      </div>
      <p className="text-sm text-muted">
        Platz 1–8 direkt ins Achtelfinale (grün), 9–24 in die Play-offs, ab 25 ausgeschieden. Die kleine Zahl neben
        dem Platz zeigt, wie viele Plätze ein Team besser (+) oder schlechter (−) steht, als es die Prognosen vor den
        bisherigen Spielen erwarten ließen; „Modell“ sind die dabei erwarteten Punkte.{" "}
        {latest && (
          <Link href={`/cl/${data.season}/${latest.current_round}`} className="underline hover:text-foreground">
            Zu den Spielen
          </Link>
        )}
      </p>
      <ClLeagueTable rows={data.rows} />
      {projected && (
        <section className="pt-4">
          <h2 className="mb-1 text-lg font-semibold">Geschätzte Abschlusstabelle der Ligaphase</h2>
          <p className="mb-4 text-sm text-muted">
            Alle offenen Spiele der Ligaphase 10.000-mal mit den Wahrscheinlichkeiten des Modells durchgespielt. Passt
            sich nach jedem Spieltag an.
          </p>
          <ClProjectionTable rows={data.rows} />
        </section>
      )}
    </div>
  );
}
