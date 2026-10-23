"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Punkteregel, TipRound } from "@/lib/api";

const ruleText = (r: Punkteregel) =>
  `Sieg ${r.sieg_tendenz}/${r.sieg_tordifferenz}/${r.exakt}, Remis ${r.remis_tendenz}/${r.exakt}`;

/** Auswahl der Kicktipp-Tipprunde: Tipps und Punkte richten sich nach ihrer Punkteregel. Die Wahl gilt für die
 * ganze App (Cookie, ein Jahr); ohne Wahl gilt die Standardrunde. */
export function TipRoundSelect({ rounds, current }: { rounds: TipRound[]; current?: string | null }) {
  const router = useRouter();
  if (!rounds.length) return null;
  const active = rounds.find((r) => r.slug === current) ?? rounds.find((r) => r.standard) ?? rounds[0];
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
      <label htmlFor="tipprunde" className="text-foreground/80">
        Tipprunde
      </label>
      <select
        id="tipprunde"
        value={active.slug}
        onChange={(e) => {
          document.cookie = `tipprunde=${encodeURIComponent(e.target.value)}; path=/; max-age=31536000; samesite=lax`;
          router.refresh();
        }}
        className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground"
      >
        {rounds.map((r) => (
          <option key={r.slug} value={r.slug}>
            {r.name}
          </option>
        ))}
      </select>
      <span className="tabular" title="Punkte für Tendenz / Tordifferenz / exaktes Ergebnis">
        {ruleText(active.punkteregel)}
        {active.bonus_points ? ` · Extratipps ${active.bonus_points} P.` : ""}
      </span>
      <Link href="/tipprunden" className="underline hover:text-foreground">
        verwalten
      </Link>
    </div>
  );
}
