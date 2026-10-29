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

/** Glatte Kurve durch die Punkte (Catmull-Rom als kubische Bézier-Stücke). */
function curve(pts: [number, number][]): string {
  return pts
    .slice(1)
    .map((p, i) => {
      const p0 = pts[Math.max(i - 1, 0)];
      const p1 = pts[i];
      const p3 = pts[Math.min(i + 2, pts.length - 1)];
      const c1 = [p1[0] + (p[0] - p0[0]) / 6, p1[1] + (p[1] - p0[1]) / 6];
      const c2 = [p[0] - (p3[0] - p1[0]) / 6, p[1] - (p3[1] - p1[1]) / 6];
      return `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    })
    .join("");
}

/** Momentum über die Spielzeit wie bei FotMob als Welle: nach oben in der Farbe des Heimteams, wenn es drückt,
 * nach unten für den Gast (Wert -100 bis 100, leicht geglättet über die Nachbarminuten). Tore, Platzverweise und
 * vergebene Elfmeter stehen als Marken an der Zeitachse über bzw. unter dem Graphen, die Halbzeit als
 * gestrichelte Linie. */
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
  const mid = H / 2;
  const x = (m: number) => ((m - 0.5) / end) * W;
  const y = (v: number) => mid - (Math.max(-100, Math.min(100, v)) / 100) * (mid - 4);
  const smooth = data.map(([m, v], i) => {
    const prev = data[i - 1]?.[1] ?? v;
    const next = data[i + 1]?.[1] ?? v;
    return [x(m), y((prev + 2 * v + next) / 4)] as [number, number];
  });
  const line = smooth.length ? `M${smooth[0][0].toFixed(1)},${smooth[0][1].toFixed(1)}${curve(smooth)}` : "";
  const area = smooth.length
    ? `M${smooth[0][0].toFixed(1)},${mid}L${smooth[0][0].toFixed(1)},${smooth[0][1].toFixed(1)}${curve(smooth)}` +
      `L${smooth[smooth.length - 1][0].toFixed(1)},${mid}Z`
    : "";
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
          <defs>
            <linearGradient id="momentum-home" x1="0" x2="0" y1="0" y2={mid} gradientUnits="userSpaceOnUse">
              <stop offset="0" style={{ stopColor: "var(--home)", stopOpacity: 0.85 }} />
              <stop offset="1" style={{ stopColor: "var(--home)", stopOpacity: 0.15 }} />
            </linearGradient>
            <linearGradient id="momentum-away" x1="0" x2="0" y1={mid} y2={H} gradientUnits="userSpaceOnUse">
              <stop offset="0" style={{ stopColor: "var(--away)", stopOpacity: 0.15 }} />
              <stop offset="1" style={{ stopColor: "var(--away)", stopOpacity: 0.85 }} />
            </linearGradient>
            <clipPath id="momentum-top">
              <rect x={0} y={0} width={W} height={mid} />
            </clipPath>
            <clipPath id="momentum-bottom">
              <rect x={0} y={mid} width={W} height={mid} />
            </clipPath>
          </defs>
          <line x1={0} x2={W} y1={mid} y2={mid} className="stroke-border" strokeWidth={1} vectorEffect="non-scaling-stroke" />
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
          <g clipPath="url(#momentum-top)">
            <path d={area} fill="url(#momentum-home)" />
            <path d={line} fill="none" style={{ stroke: "var(--home)" }} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          </g>
          <g clipPath="url(#momentum-bottom)">
            <path d={area} fill="url(#momentum-away)" />
            <path d={line} fill="none" style={{ stroke: "var(--away)" }} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          </g>
          {data.map(([m, v]) => (
            <rect key={m} x={x(m) - W / end / 2} width={W / end} y={0} height={H} fill="transparent">
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
