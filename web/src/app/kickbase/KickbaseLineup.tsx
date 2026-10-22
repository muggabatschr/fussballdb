import { Card } from "@/components/Card";
import { TeamLogo } from "@/components/TeamLogo";
import type { KickbaseLineup as Lineup } from "@/lib/api";
import { num } from "@/lib/format";

const POS: Record<string, string> = { TW: "Tor", ABW: "Abwehr", MF: "Mittelfeld", ST: "Sturm" };
const GRUND: Record<string, string> = { injury: "verletzt", suspension: "gesperrt" };

/** Beste Elf aus dem eigenen Kader für den nächsten Spieltag, dazu Ausfälle im Kader. */
export function KickbaseLineup({ l }: { l: Lineup }) {
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="whitespace-nowrap text-sm font-medium">
          Deine Aufstellung{l.formation ? ` · ${l.formation}` : ""}
        </h2>
        {l.punkte != null && <span className="text-xs text-muted tabular">{l.punkte} erwartete Punkte</span>}
      </div>
      {l.ausfaelle.length > 0 && (
        <p className="rounded-md bg-away/15 px-3 py-2 text-xs text-away">
          Achtung, im Kader fehlt: {l.ausfaelle.map((a) => `${a.name} (${GRUND[a.grund] ?? a.grund})`).join(", ")}
        </p>
      )}
      {l.hinweis && <p className="text-xs text-muted">{l.hinweis}</p>}
      {l.elf.length > 0 && (
        <div className="space-y-2">
          {(["TW", "ABW", "MF", "ST"] as const).map((p) => {
            const players = l.elf.filter((x) => x.position === p);
            if (!players.length) return null;
            return (
              <div key={p} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="w-20 shrink-0 text-xs text-muted">{POS[p]}</span>
                {players.map((x) => (
                  <span key={x.name} className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border px-2 py-1" title={`gegen ${x.gegner.join(", ")} · Einsatzchance ${Math.round(x.einsatz * 100)} %`}>
                    <TeamLogo name={x.team_name} size={16} />
                    <span className="truncate">{x.name}</span>
                    <span className="text-xs text-muted tabular">{num(x.kb_punkte, 0)}</span>
                  </span>
                ))}
              </div>
            );
          })}
        </div>
      )}
      {l.bank.length > 0 && (
        <p className="text-xs text-muted">Bank: {l.bank.map((x) => `${x.name} (${num(x.kb_punkte, 0)})`).join(", ")}</p>
      )}
      <p className="text-[11px] text-muted">
        Je Formation die besten fitten Spieler nach erwarteten Kickbase-Punkten am nächsten Spieltag; gewählt wird die
        Formation mit der höchsten Summe.
      </p>
    </Card>
  );
}
