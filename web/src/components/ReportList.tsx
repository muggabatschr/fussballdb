import Link from "next/link";
import type { ReportHit } from "@/lib/api";

/** Gefundene Spielberichte im Chat: Schlagzeile, Paarung und Datum mit Link zur Detailseite, der Bericht aufklappbar. */
export function ReportList({ hits }: { hits: ReportHit[] }) {
  if (!hits.length) return <p className="text-xs text-muted">Keine passenden Spielberichte gefunden.</p>;
  return (
    <ul className="space-y-1 text-sm">
      {hits.map((h) => {
        const [head, lead = "", ...rest] = h.bericht.split("\n");
        const game = lead.slice(lead.lastIndexOf(": ") + 2).replace(/\.$/, ""); // "Heim – Gast 1:0 (0:0)"
        return (
          <li key={h.match_id}>
            <details className="group rounded-lg border border-border bg-surface px-3 py-2">
              <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
                <span className="inline-block text-xs text-muted transition-transform group-open:rotate-90">▸</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{head}</span>
                  <span className="block truncate text-xs text-muted">
                    {game} · {new Date(h.datum).toLocaleDateString("de-DE")}
                  </span>
                </span>
                <Link href={h.link} className="shrink-0 text-xs text-muted underline hover:text-foreground">
                  Spiel
                </Link>
              </summary>
              <div className="mt-2 space-y-1 text-xs text-muted">
                {[lead, ...rest].map((l) => (
                  <p key={l}>{l}</p>
                ))}
              </div>
            </details>
          </li>
        );
      })}
    </ul>
  );
}
