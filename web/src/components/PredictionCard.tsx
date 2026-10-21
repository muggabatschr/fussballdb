import type { Prediction } from "@/lib/api";
import { kickoff, num, pct } from "@/lib/format";
import { Card } from "./Card";
import { ProbabilityBar } from "./ProbabilityBar";
import { TeamName } from "./TeamName";
import { WhyTip } from "./WhyTip";

export function PredictionCard({ home, away, p }: { home: string; away: string; p: Prediction }) {
  const market = p.marktquoten.find((m) => m.bookmaker === "Avg" && !m.is_closing);
  const marketProbs = market && (() => {
    const inv = [1 / market.home, 1 / market.draw, 1 / market.away];
    const sum = inv[0] + inv[1] + inv[2];
    return inv.map((v) => v / sum);
  })();
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between gap-2 whitespace-nowrap text-xs text-muted">
        <span className="truncate">
          {typeof p.spiel !== "string" ? `${p.spiel.matchday}. Spieltag · ${kickoff(p.spiel.kickoff)}` : "Prognose"}
        </span>
        {p.tipp && (
          <span className="shrink-0 tabular">
            Tipp <span className="text-sm font-semibold text-foreground">{p.tipp}</span>
          </span>
        )}
      </div>
      <h3 className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 font-semibold">
        <TeamName name={home} short logoSize={22} />
        <span className="text-muted">–</span>
        <TeamName name={away} short logoSize={22} align="end" className="justify-self-end" />
      </h3>
      <ProbabilityBar home={p.p_home} draw={p.p_draw} away={p.p_away} />
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4 tabular">
        <div>
          <dt className="text-xs text-muted">Erwartete Tore</dt>
          <dd>
            {num(p.exp_goals[0], 1)} : {num(p.exp_goals[1], 1)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Über 2,5 Tore</dt>
          <dd>{pct(p.p_over25)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Beide treffen</dt>
          <dd>{pct(p.p_btts)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Elo</dt>
          <dd>
            {Math.round(p.teilmodelle.elo.elo_home)} : {Math.round(p.teilmodelle.elo.elo_away)}
          </dd>
        </div>
      </dl>
      <p className="text-xs text-muted">
        Wahrscheinlichste Ergebnisse: {p.wahrscheinlichste_ergebnisse.slice(0, 3).join(", ")}
      </p>
      {marketProbs && (
        <p className="text-xs text-muted tabular">
          Markt (Ø-Quoten): 1 {pct(marketProbs[0])} · X {pct(marketProbs[1])} · 2 {pct(marketProbs[2])}
        </p>
      )}
      <WhyTip tip={p.tipp} lines={p.begruendung} />
    </Card>
  );
}
