import { Card } from "@/components/Card";
import { TeamLogo } from "@/components/TeamLogo";
import type { KickbaseLineup as Lineup, KickbaseSwap } from "@/lib/api";
import { num } from "@/lib/format";

const POS: Record<string, string> = { TW: "Tor", ABW: "Abwehr", MF: "Mittelfeld", ST: "Sturm" };
const ORDER = ["TW", "ABW", "MF", "ST"] as const;
const GRUND: Record<string, string> = { injury: "verletzt", suspension: "gesperrt" };
const mio = (v: number | null | undefined) => (v == null ? "–" : `${num(v / 1e6, 1)} Mio`);

type Chip = { name: string; position: string; team_name: string; kb_punkte: number | null; ausfall?: string | null; title?: string };

/** Spieler einer Elf nach Position, Ausfälle rot mit 0 Punkten. */
function Rows({ players, empty = {} }: { players: Chip[]; empty?: Partial<Record<string, number>> }) {
  return (
    <div className="space-y-2">
      {ORDER.map((p) => {
        const list = players.filter((x) => x.position === p);
        const free = empty[p] ?? 0;
        if (!list.length && !free) return null;
        return (
          <div key={p} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="w-20 shrink-0 text-xs text-muted">{POS[p]}</span>
            {list.map((x) => (
              <span
                key={x.name}
                className={`inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 ${x.ausfall ? "border-away/50 text-away" : "border-border"}`}
                title={x.ausfall ? `${GRUND[x.ausfall] ?? x.ausfall}, bringt keine Punkte` : x.title}
              >
                <TeamLogo name={x.team_name} size={16} />
                <span className="truncate">{x.name}</span>
                <span className="text-xs text-muted tabular">{x.ausfall ? GRUND[x.ausfall] ?? "fällt aus" : num(x.kb_punkte ?? 0, 0)}</span>
              </span>
            ))}
            {Array.from({ length: free }, (_, i) => (
              <span key={`frei${i}`} className="rounded-md border border-dashed border-border px-2 py-1 text-xs text-muted">
                leer
              </span>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function SwapLine({ s }: { s: KickbaseSwap }) {
  const formation = s.formation_nachher !== s.formation_vorher ? `, Formation ${s.formation_vorher} → ${s.formation_nachher}` : "";
  return (
    <li>
      <span className="text-foreground">{s.verkauf}</span> ({s.verkauf_position}, {mio(s.verkauf_wert)}) verkaufen,{" "}
      <span className="text-foreground">{s.kauf}</span> ({s.kauf_position}, {s.kauf_team}, ab {mio(s.kauf_preis)}) kaufen:{" "}
      <span className="font-semibold text-foreground">+{num(s.mehr_punkte, 0)} Pkt</span>
      {formation}, Budget danach {mio(s.budget_danach)}
    </li>
  );
}

/** Aktuelle Elf aus Kickbase, beste Elf aus dem eigenen Kader für den nächsten Spieltag, Budget und
 * Tauschvorschläge (verkaufen und vom Markt kaufen, auch mit Wechsel der Formation). */
export function KickbaseLineup({ l }: { l: Lineup }) {
  const now = l.aktuell;
  const diff = now && l.punkte != null ? l.punkte - now.punkte : null;
  return (
    <Card className="space-y-4">
      {l.budget != null && (
        <p className={`rounded-md px-3 py-2 text-xs ${l.budget < 0 ? "bg-away/15 text-away" : "text-muted"}`}>
          Budget {mio(l.budget)}
          {l.budget < 0 && ": negativ. Liegt es beim Anpfiff unter 0, gibt es an diesem Spieltag keine Punkte."}
        </p>
      )}
      {l.ausfaelle.length > 0 && (
        <p className="rounded-md bg-away/15 px-3 py-2 text-xs text-away">
          Achtung, im Kader fehlt: {l.ausfaelle.map((a) => `${a.name} (${GRUND[a.grund] ?? a.grund})`).join(", ")}
        </p>
      )}

      {now && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="whitespace-nowrap text-sm font-medium">
              Aufgestellt in Kickbase{now.formation ? ` · ${now.formation}` : ""}
            </h2>
            <span className="text-xs text-muted tabular">{now.punkte} erwartete Punkte</span>
          </div>
          <Rows players={now.elf} />
        </div>
      )}

      <div className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="whitespace-nowrap text-sm font-medium">
            {now ? "Beste Elf aus deinem Kader" : "Deine Aufstellung"}
            {l.formation ? ` · ${l.formation}` : ""}
          </h2>
          {l.punkte != null && (
            <span className="text-xs text-muted tabular">
              {l.punkte} erwartete Punkte
              {diff != null && diff !== 0 && ` (${diff > 0 ? "+" : ""}${diff} gegenüber jetzt)`}
            </span>
          )}
        </div>
        {l.hinweis && <p className="text-xs text-muted">{l.hinweis}</p>}
        {l.elf.length > 0 && (
          <Rows
            players={l.elf.map((x) => ({ ...x, title: `gegen ${x.gegner.join(", ")} · Einsatzchance ${Math.round(x.einsatz * 100)} %` }))}
            empty={l.fehlt}
          />
        )}
        {l.bank.length > 0 && (
          <p className="text-xs text-muted">Bank: {l.bank.map((x) => `${x.name} (${num(x.kb_punkte, 0)})`).join(", ")}</p>
        )}
      </div>

      {l.tausch && l.tausch.length > 0 && (
        <div className="space-y-1.5">
          <h2 className="whitespace-nowrap text-sm font-medium">Tauschvorschläge</h2>
          <ul className="space-y-1 text-xs text-muted">
            {l.tausch.slice(0, 5).map((s) => (
              <SwapLine key={`${s.verkauf_id}-${s.kauf}`} s={s} />
            ))}
          </ul>
        </div>
      )}

      <p className="text-[11px] text-muted">
        Erwartete Kickbase-Punkte am nächsten Spieltag. Die beste Elf nimmt je Formation die besten fitten Spieler und
        wählt die Formation mit der höchsten Summe. Tauschvorschläge: Verkauf an Kickbase zum Marktwert, Kauf zum
        Angebotspreis auf dem Markt (Gebote können höher liegen), je verkauftem Spieler der Kauf, der die beste Elf am
        meisten verbessert, nur wenn das Budget danach nicht negativ ist.
      </p>
    </Card>
  );
}
