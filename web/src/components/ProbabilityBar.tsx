import { pct } from "@/lib/format";

export function ProbabilityBar({ home, draw, away }: { home: number; draw: number; away: number }) {
  const segments = [
    { key: "1", value: home, className: "bg-home" },
    { key: "X", value: draw, className: "bg-draw" },
    { key: "2", value: away, className: "bg-away" },
  ];
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full" role="img" aria-label={`Heimsieg ${pct(home)}, Remis ${pct(draw)}, Auswärtssieg ${pct(away)}`}>
        {segments.map((s) => (
          <div key={s.key} className={s.className} style={{ width: `${s.value * 100}%` }} />
        ))}
      </div>
      <div className="mt-1 flex justify-between whitespace-nowrap text-xs text-muted tabular">
        <span>1 · {pct(home)}</span>
        <span>X · {pct(draw)}</span>
        <span>2 · {pct(away)}</span>
      </div>
    </div>
  );
}
