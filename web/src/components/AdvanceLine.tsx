import type { MatchdayGame } from "@/lib/api";
import { pct } from "@/lib/format";
import { shortName } from "@/lib/teams";

/** K.-o.-Spiel (Pokal): wer wahrscheinlich weiterkommt, mit Verlängerung und Elfmeterschießen. Die Balken
 * darüber und der Tipp gelten für die 90 Minuten. */
export function AdvanceLine({ g }: { g: MatchdayGame }) {
  const w = g.weiter;
  if (!w) return null;
  const fav = w.home >= w.away ? g.home : g.away;
  return (
    <p
      className="truncate text-xs text-muted tabular"
      title="Chance aufs Weiterkommen nach 90 Minuten, Verlängerung (ein Drittel der Torerwartung) und Elfmeterschießen (50:50). Prognose und Tipp oben gelten für die 90 Minuten."
    >
      Weiter: <span className="font-medium text-foreground">{shortName(fav)} {pct(Math.max(w.home, w.away))}</span>
      {" · "}Verlängerung {pct(w.verlaengerung)}, Elfmeterschießen {pct(w.elfmeterschiessen)}
    </p>
  );
}
