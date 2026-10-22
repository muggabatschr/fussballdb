"use client";

import Link from "next/link";
import { CurrentLink } from "./CurrentLink";
import { useRouter } from "next/navigation";
import type { ClSeason } from "@/lib/api";
import { COMPETITIONS, type CompCode } from "@/lib/competitions";

/** Saison und Runde eines Wettbewerbs wählen (CL: Ligaphase, Play-offs, K.-o.-Runden; 2. Liga; Pokal). */
export function ClNav({ seasons, season, round, comp = "CL" }: { seasons: ClSeason[]; season: number; round: number; comp?: CompCode }) {
  const router = useRouter();
  const c = COMPETITIONS[comp];
  const href = (s: number, r: number) => `${c.base}/${s}/${r}`;
  const current = seasons.find((s) => s.season === season);
  const rounds = current?.rounds ?? [];
  const i = rounds.findIndex((r) => r.round_no === round);
  const prev = i > 0 ? rounds[i - 1] : null;
  const next = i >= 0 && i < rounds.length - 1 ? rounds[i + 1] : null;
  const arrow = "rounded-lg border border-border bg-surface px-3 py-1.5 text-sm";
  const currentHref = href(season, current?.current_round ?? round);
  const toCurrent = Boolean(current && round !== current.current_round && current.rounds.some((r) => !r.finished));

  return (
    <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 sm:w-auto">
      <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
        <CurrentLink href={currentHref} show={toCurrent} title="zur aktuellen Runde" className="max-sm:hidden" />
        <select
          aria-label="Saison"
          value={season}
          onChange={(e) => {
            const s = seasons.find((x) => x.season === Number(e.target.value));
            if (s) router.push(href(s.season, s.current_round));
          }}
          className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm"
        >
          {seasons.map((s) => (
            <option key={s.season} value={s.season}>
              {s.label}
            </option>
          ))}
        </select>

        {prev ? (
          <Link href={href(season, prev.round_no)} className={`${arrow} hover:border-accent`} aria-label="Vorherige Runde">
            ←
          </Link>
        ) : (
          <span className={`${arrow} opacity-40`}>←</span>
        )}

        <select
          aria-label="Runde"
          value={round}
          onChange={(e) => router.push(href(season, Number(e.target.value)))}
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm sm:w-52 sm:flex-none"
        >
          {rounds.map((r) => (
            <option key={r.round_no} value={r.round_no}>
              {r.round_name}
            </option>
          ))}
        </select>

        {next ? (
          <Link href={href(season, next.round_no)} className={`${arrow} hover:border-accent`} aria-label="Nächste Runde">
            →
          </Link>
        ) : (
          <span className={`${arrow} opacity-40`}>→</span>
        )}
      </div>

      <div className="flex gap-4">
        <CurrentLink href={currentHref} show={toCurrent} title="zur aktuellen Runde" className="sm:hidden" />
        <Link href={`${c.base}/tipps/${season}/${round}`} className="whitespace-nowrap text-sm text-muted underline hover:text-foreground">
          Tipp-Zettel
        </Link>
        {c.table && (
          <Link href={`${c.base}/tabelle/${season}`} className="whitespace-nowrap text-sm text-muted underline hover:text-foreground">
            {c.table}
          </Link>
        )}
      </div>
    </div>
  );
}
