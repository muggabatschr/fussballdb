import type { BonusQuestion } from "@/lib/api";
import { TeamName } from "./TeamName";

function Picks({ label, picks, strong = false }: { label: string; picks: { team: string; p: number }[]; strong?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular">
      <span className={`w-28 shrink-0 ${strong ? "font-medium text-foreground/80" : "text-muted"}`}>{label}</span>
      {picks.map((x) => (
        <span key={x.team} className={`inline-flex items-center gap-1 ${strong ? "" : "opacity-70"}`}>
          <TeamName name={x.team} short link={false} logoSize={14} />
          <span className="text-muted">{x.p < 1 ? "<1" : Math.round(x.p)} %</span>
        </span>
      ))}
    </div>
  );
}

/** Extratipps (Bonusfragen) einer Tipprunde: die wahrscheinlichsten Antworten mit dem Wissen zum Tippschluss
 * (darauf kommt es beim Tippen an) und zum Vergleich der Stand heute. */
export function BonusList({ questions }: { questions: BonusQuestion[] }) {
  if (!questions.length) return <p className="text-sm text-muted">Keine Bonusfragen gefunden.</p>;
  return (
    <ul className="divide-y divide-border text-sm">
      {questions.map((q) => (
        <li key={q.frage} className="space-y-1 py-2">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="font-medium">{q.frage}</span>
            <span className="text-xs text-muted">Tippschluss {q.termin}</span>
          </div>
          {q.antworten.length > 0 && (
            <p className="text-xs text-muted">
              Entschieden: <span className="text-foreground/80">{q.antworten.join(", ")}</span>
            </p>
          )}
          {q.prognose?.length ? <Picks label="Zum Tippschluss" picks={q.prognose} strong /> : null}
          {q.heute?.length ? <Picks label="Stand heute" picks={q.heute} /> : null}
          {q.hinweis && <p className="text-xs text-muted">{q.hinweis}</p>}
        </li>
      ))}
    </ul>
  );
}
