import Link from "next/link";
import { getCompMatchDetail, getCompRound, getCompRounds, getCompTable, load } from "@/lib/api";
import { COMPETITIONS, type CompCode } from "@/lib/competitions";
import { ErrorBox } from "./Card";
import { ClLeagueTable, ClProjectionTable, ClTableSeasons } from "./ClTable";
import { ClView } from "./ClView";
import { CompetitionTabs } from "./CompetitionTabs";
import { TipSheet } from "./TipSheet";
import { Legend, TERMS } from "./Legend";
import { MatchDetailView } from "./MatchDetail";

/** Runde eines Wettbewerbs; ohne Angaben die aktuelle Runde der neuesten Saison. */
export async function CompRoundPage({ comp, season, round }: { comp: CompCode; season?: number; round?: number }) {
  const res = await load(async () => {
    const seasons = await getCompRounds(comp);
    const s = seasons.find((x) => x.season === season) ?? seasons[0];
    return [seasons, await getCompRound(comp, s.season, round ?? s.current_round)] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data] = res.data;
  return <ClView seasons={seasons} data={data} comp={comp} />;
}

/** Tabelle mit Modell-Platz und geschätzter Abschlusstabelle (CL-Ligaphase, 2. Liga). */
export async function CompTablePage({ comp, season }: { comp: CompCode; season?: number }) {
  const c = COMPETITIONS[comp];
  const res = await load(async () => {
    const seasons = await getCompRounds(comp);
    const s = season ?? seasons[0].season;
    return [seasons, await getCompTable(comp, s)] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data] = res.data;
  const projected = data.rows.some((r) => r.prognose_platz != null);
  const current = seasons.find((s) => s.season === data.season);
  const zoneText = (data.zonen ?? []).map((z) => `${z.von}${z.bis > z.von ? `–${z.bis}` : ""} ${z.label}`).join(", ");
  return (
    <div className="space-y-4">
      <CompetitionTabs active={comp} />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="whitespace-nowrap text-xl font-semibold">
          {comp === "CL" ? "Ligaphase" : "Tabelle"} <span className="text-muted">{c.short} {data.label}</span>
        </h1>
        <ClTableSeasons seasons={seasons} current={data.season} base={c.base} />
      </div>
      <p className="text-sm text-muted">
        Zonen: {zoneText}. Die kleine Zahl neben dem Platz zeigt, wie viele Plätze ein Team besser (+) oder schlechter
        (−) steht, als es die Prognosen vor den bisherigen Spielen erwarten ließen; „Modell“ sind die dabei erwarteten
        Punkte.{" "}
        {current && (
          <Link href={`${c.base}/${data.season}/${current.current_round}`} className="underline hover:text-foreground">
            Zu den Spielen
          </Link>
        )}
      </p>
      <ClLeagueTable rows={data.rows} zones={data.zonen} />
      <Legend items={[TERMS.sp, TERMS.tore, TERMS.pkt, TERMS.modell, TERMS.platz]} />
      {projected && (
        <section className="pt-4">
          <h2 className="mb-1 text-lg font-semibold">Geschätzte Abschlusstabelle</h2>
          <p className="mb-4 text-sm text-muted">
            Alle offenen Spiele 10.000-mal mit den Wahrscheinlichkeiten des Modells durchgespielt. Passt sich nach jedem
            Spieltag an.
          </p>
          <ClProjectionTable rows={data.rows} zones={data.zonen} />
          <Legend
            items={[
              TERMS.erwPkt,
              TERMS.heute,
              ...(data.zonen ?? []).map(
                (z): [string, string] => [z.label, `Chance auf Platz ${z.von}${z.bis > z.von ? `–${z.bis}` : ""} in Prozent`],
              ),
            ]}
          />
        </section>
      )}
    </div>
  );
}

/** Tipp-Zettel einer Runde (2. Liga, CL, Pokal); ohne Angaben die aktuelle Runde. */
export async function CompTipsPage({ comp, season, round }: { comp: CompCode; season?: number; round?: number }) {
  const c = COMPETITIONS[comp];
  const res = await load(async () => {
    const seasons = await getCompRounds(comp);
    const s = seasons.find((x) => x.season === season) ?? seasons[0];
    return [s, await getCompRound(comp, s.season, round ?? s.current_round)] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [s, data] = res.data;
  return (
    <TipSheet
      title={data.round_name}
      subtitle={`${c.name} ${s.label}`}
      games={data.games}
      backHref={`${c.base}/${data.season}/${data.round_no}`}
      backLabel="zur Runde"
      fileName={`tipps-${c.base.slice(1)}-${data.season}-${data.round_no}.png`}
    />
  );
}

/** Detailseite eines Spiels (2. Liga, CL, Pokal). */
export async function CompMatchPage({ comp, id }: { comp: CompCode; id: number }) {
  const c = COMPETITIONS[comp];
  const res = await load(() => getCompMatchDetail(comp, id));
  if (!res.ok) return <ErrorBox message={res.error} />;
  const d = res.data;
  const g = d.game;
  const label = `${g.season}/${String((g.season + 1) % 100).padStart(2, "0")}`;
  return (
    <MatchDetailView
      d={d}
      meta={`${c.name} · ${g.round_name} · ${label}`}
      backHref={`${c.base}/${g.season}/${g.round_no}`}
      backLabel={`zur Runde (${g.round_name})`}
    />
  );
}
