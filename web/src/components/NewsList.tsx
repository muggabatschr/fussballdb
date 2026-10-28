import type { NewsItem } from "@/lib/api";
import { shortName } from "@/lib/teams";

const when = (iso: string) =>
  new Date(iso).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });

/** Presse-Meldungen: Überschrift als Link zur Quelle, darunter Zeitung und Zeit; Lokalzeitungen und Vereinsseiten
 * markiert. Es gibt nur Überschriften (Google News), keine Artikeltexte. */
export function NewsList({ items, showTeam = false }: { items: NewsItem[]; showTeam?: boolean }) {
  if (!items.length) return <p className="text-xs text-muted">Keine Meldungen in den letzten Tagen.</p>;
  return (
    <ul className="space-y-2 text-sm">
      {items.map((n) => (
        <li key={`${n.titel}-${n.datum}`} className="leading-snug">
          {n.link ? (
            <a href={n.link} target="_blank" rel="noopener noreferrer" className="hover:underline">
              {n.titel}
            </a>
          ) : (
            n.titel
          )}
          <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted">
            {n.art && (
              <span className="rounded bg-accent/15 px-1 text-[10px] font-medium text-foreground">
                {n.art === "lokal" ? "Lokal" : "Verein"}
              </span>
            )}
            {showTeam && n.verein && <span>{shortName(n.verein)} ·</span>}
            <span>{n.quelle ?? "unbekannte Quelle"}</span>
            <span>· {when(n.datum)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
