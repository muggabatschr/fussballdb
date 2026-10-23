import type { MatchEvent } from "@/lib/api";
import { TeamName } from "./TeamName";

const SYMBOL: Record<MatchEvent["art"], string> = {
  tor: "⚽",
  eigentor: "⚽",
  rot: "🟥",
  gelbrot: "🟥",
  elfmeter_vergeben: "✕",
};
const LABEL: Record<MatchEvent["art"], string> = {
  tor: "Tor",
  eigentor: "Eigentor",
  rot: "Rote Karte",
  gelbrot: "Gelb-Rot",
  elfmeter_vergeben: "Elfmeter vergeben",
};

/** Momentum über die Spielzeit wie bei FotMob: je Minute ein Balken nach oben, wenn das Heimteam drückt, nach
 * unten für den Gast (Wert -100 bis 100). Tore, Platzverweise und vergebene Elfmeter stehen als Marken an der
 * Zeitachse über bzw. unter dem Graphen, die Halbzeit als gestrichelte Linie. */
export function Momentum({
  data,
  events,
  home,
  away,
}: {
  data: [number, number][];
  events: MatchEvent[];
  home: string;
  away: string;
}) {
  const end = Math.max(90, ...data.map(([m]) => m), ...events.map((e) => e.pos));
  const W = 1000;
  const H = 200;
  const bar = (W / end) * 0.8;
  const x = (m: number) => ((m - 0.5) / end) * W;
  const left = (m: number) => `${(Math.min(Math.max(m - 0.5, 0), end) / end) * 100}%`;
  const markers = (heim: boolean) =>
    events
      .filter((e) => e.heim === heim)
      .map((e, i) => (
        <span
          key={i}
          className={`absolute -translate-x-1/2 text-xs leading-none ${e.art === "eigentor" ? "opacity-60 grayscale" : ""}`}
          style={{ left: left(e.pos) }}
          title={`${e.minute}${e.nachspiel ? `+${e.nachspiel}` : ""}. ${LABEL[e.art]}: ${e.spieler}${
            e.stand ? ` (${e.stand[0]}:${e.stand[1]})` : ""
          }`}
        >
          {SYMBOL[e.art]}
        </span>
      ));
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center gap-2 text-xs">
        <span className="inline-block h-2 w-2 rounded-sm bg-home" />
        <TeamName name={home} short logoSize={14} link={false} />
      </div>
      <div className="relative mt-1 h-4">{markers(true)}</div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-32 w-full sm:h-40" role="img" aria-label="Momentum über die Spielzeit">
          <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="stroke-border" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <line
            x1={(45 / end) * W}
            x2={(45 / end) * W}
            y1={0}
            y2={H}
            className="stroke-muted"
            strokeDasharray="4 4"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
          {data.map(([m, v]) => (
            <rect
              key={m}
              x={x(m) - bar / 2}
              width={bar}
              y={v >= 0 ? H / 2 - (v / 100) * (H / 2) : H / 2}
              height={(Math.abs(v) / 100) * (H / 2)}
              className={v >= 0 ? "fill-home" : "fill-away"}
            >
              <title>{`${Math.floor(m)}. Minute: ${v >= 0 ? home : away} ${Math.abs(v)}`}</title>
            </rect>
          ))}
        </svg>
      </div>
      <div className="relative mt-1 h-4">{markers(false)}</div>
      <div className="flex items-center gap-2 text-xs">
        <span className="inline-block h-2 w-2 rounded-sm bg-away" />
        <TeamName name={away} short logoSize={14} link={false} />
      </div>
      <div className="relative mt-1 h-4 text-[10px] text-muted tabular-nums">
        {[0, 15, 30, 45, 60, 75, 90].map((m) => (
          <span key={m} className={`absolute ${m ? "-translate-x-1/2" : ""}`} style={{ left: `${(m / end) * 100}%` }}>
            {m}′
          </span>
        ))}
      </div>
    </div>
  );
}
