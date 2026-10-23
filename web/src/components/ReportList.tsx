import Link from "next/link";
import type { ReportHit } from "@/lib/api";

/** Gefundene Spielberichte im Chat: Kopfzeile mit Link zur Detailseite, der Bericht aufklappbar. */
export function ReportList({ hits }: { hits: ReportHit[] }) {
  if (!hits.length) return <p className="text-xs text-muted">Keine passenden Spielberichte gefunden.</p>;
  return (
    <ul className="space-y-1 text-sm">
      {hits.map((h) => {
        const [head, ...rest] = h.bericht.split("\n");
        return (
          <li key={h.match_id}>
            <details className="group rounded-lg border border-border bg-surface px-3 py-2">
              <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
                <span className="inline-block text-xs text-muted transition-transform group-open:rotate-90">▸</span>
                <span className="min-w-0 flex-1 truncate">{head.replace(/^Bundesliga /, "")}</span>
                <Link href={h.link} className="shrink-0 text-xs text-muted underline hover:text-foreground">
                  Spiel
                </Link>
              </summary>
              <div className="mt-2 space-y-1 text-xs text-muted">
                {rest.map((l) => (
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
