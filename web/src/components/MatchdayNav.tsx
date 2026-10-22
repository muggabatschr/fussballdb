"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Season } from "@/lib/api";

const href = (season: number, md: number) => `/spieltag/${season}/${md}`;

export function MatchdayNav({ seasons, season, matchday }: { seasons: Season[]; season: number; matchday: number }) {
  const router = useRouter();
  const current = seasons.find((s) => s.start_year === season);
  const max = current?.matchdays ?? 34;
  const arrow = "rounded-lg border border-border bg-surface px-3 py-1.5 text-sm";

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <div className="flex shrink-0 items-center gap-2">
        <select
          aria-label="Saison"
          value={season}
          onChange={(e) => {
            const s = seasons.find((x) => x.start_year === Number(e.target.value));
            if (s) router.push(href(s.start_year, s.current_matchday));
          }}
          className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm"
        >
          {seasons.map((s) => (
            <option key={s.start_year} value={s.start_year}>
              {s.label}
            </option>
          ))}
        </select>

        {matchday > 1 ? (
          <Link href={href(season, matchday - 1)} className={`${arrow} hover:border-accent`} aria-label="Vorheriger Spieltag">
            ←
          </Link>
        ) : (
          <span className={`${arrow} opacity-40`}>←</span>
        )}

        <select
          aria-label="Spieltag"
          value={matchday}
          onChange={(e) => router.push(href(season, Number(e.target.value)))}
          className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm"
        >
          {Array.from({ length: max }, (_, i) => i + 1).map((md) => (
            <option key={md} value={md}>
              {md}. Spieltag
            </option>
          ))}
        </select>

        {matchday < max ? (
          <Link href={href(season, matchday + 1)} className={`${arrow} hover:border-accent`} aria-label="Nächster Spieltag">
            →
          </Link>
        ) : (
          <span className={`${arrow} opacity-40`}>→</span>
        )}
      </div>

      <div className="flex gap-4">
        <Link href={`/tipps/${season}/${matchday}`} className="whitespace-nowrap text-sm text-muted underline hover:text-foreground">
          Tipp-Zettel
        </Link>
        {current && !current.finished && matchday !== current.current_matchday && (
          <Link href={href(season, current.current_matchday)} className="whitespace-nowrap text-sm text-muted hover:text-foreground">
            zum aktuellen Spieltag
          </Link>
        )}
      </div>
    </div>
  );
}
