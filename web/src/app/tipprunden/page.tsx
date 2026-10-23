import { Suspense } from "react";
import { BonusList } from "@/components/BonusList";
import { Card, ErrorBox } from "@/components/Card";
import { getTipBonus, getTipRounds, load } from "@/lib/api";
import { AddTipRound, RoundActions } from "./TipRoundManager";

async function Rounds() {
  const res = await load(async () => {
    const rounds = await getTipRounds();
    const bonus = await Promise.all(rounds.map((r) => (r.bonus_points ? getTipBonus(r.slug).catch(() => null) : null)));
    return rounds.map((r, i) => ({ r, bonus: bonus[i] }));
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  if (!res.data.length) return <p className="text-sm text-muted">Noch keine Tipprunde hinterlegt.</p>;
  return (
    <div className="space-y-3">
      {res.data.map(({ r, bonus }) => (
        <Card key={r.slug} className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="font-medium">
                {r.name} {r.standard && <span className="ml-1 rounded bg-accent/15 px-1.5 text-xs text-accent">Standard</span>}
              </h2>
              {r.url && (
                <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-xs text-muted underline hover:text-foreground">
                  {r.url}
                </a>
              )}
            </div>
            <RoundActions round={r} />
          </div>
          <table className="text-sm tabular">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="pr-4" />
                <th className="pr-4 font-normal">Tendenz</th>
                <th className="pr-4 font-normal">Tordifferenz</th>
                <th className="font-normal">Ergebnis</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="pr-4 text-muted">Sieg</td>
                <td className="pr-4">{r.punkteregel.sieg_tendenz}</td>
                <td className="pr-4">{r.punkteregel.sieg_tordifferenz}</td>
                <td>{r.punkteregel.exakt}</td>
              </tr>
              <tr>
                <td className="pr-4 text-muted">Remis</td>
                <td className="pr-4">{r.punkteregel.remis_tendenz}</td>
                <td className="pr-4 text-muted">–</td>
                <td>{r.punkteregel.exakt}</td>
              </tr>
            </tbody>
          </table>
          <p className="text-xs text-muted">
            Tippschluss {r.lead_minutes ? `${r.lead_minutes} Minuten vor dem Anpfiff` : "mit dem Anpfiff"}
            {r.bonus_points ? ` · Extratipps mit ${r.bonus_points} Punkten je richtiger Antwort` : " · keine Extratipps"}
          </p>
          {bonus && bonus.fragen.length > 0 && (
            <section>
              <h3 className="mb-1 text-sm font-medium">Extratipps: wahrscheinlichste Antworten</h3>
              <BonusList questions={bonus.fragen} />
              <p className="mt-1 text-xs text-muted">
                „Zum Tippschluss“ nutzt nur, was bis zum Tippschluss bekannt war (Spiele, Kaderwerte, gemeldete
                Verletzte), und spielt die ganze Saison 10.000-mal durch; so hätte man tippen sollen. „Stand heute“ ist
                die aktuelle Hochrechnung. Der Torschützenkönig kommt aus den Torraten der Spieler (xG und Tore), der
                erste Trainerwechsel ist nur eine Näherung (wer nach dem 8. Spieltag unten steht).
              </p>
            </section>
          )}
        </Card>
      ))}
    </div>
  );
}

export default function Page() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Tipprunden</h1>
        <p className="text-sm text-muted">
          Kicktipp-Runden mit ihrer Punkteregel. Tipps und Punkte richten sich nach der oben auf dem Spieltag gewählten
          Runde; der Tipp ist jeweils das Ergebnis mit den meisten erwarteten Punkten nach ihrer Regel. Die Regeln werden
          von der öffentlichen Seite „Spielregeln“ der Runde gelesen.
        </p>
      </div>
      <Card>
        <AddTipRound />
      </Card>
      <Suspense fallback={<p className="text-muted">Lade Tipprunden …</p>}>
        <Rounds />
      </Suspense>
    </div>
  );
}
