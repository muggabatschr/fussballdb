"use client";

import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { FormGame } from "@/lib/api";
import { shortName } from "@/lib/teams";

/** xG und xGA je Spiel, ältestes links. `active` ist der Index in `games` (jüngstes zuerst, wie in der Tabelle);
 * dieses Spiel wird hervorgehoben, die anderen treten zurück. `onActive` meldet das Spiel unter der Maus. */
export function XgChart({
  games,
  active = null,
  onActive,
}: {
  games: FormGame[];
  active?: number | null;
  onActive?: (index: number | null) => void;
}) {
  const n = games.length;
  const data = [...games].reverse().map((g) => ({
    name: `${g.ort === "H" ? "" : "@"}${shortName(g.gegner)}`,
    xG: g.xg,
    xGA: g.xga,
  }));
  const highlighted = active == null ? null : n - 1 - active; // Index im Diagramm
  const opacity = (i: number) => (highlighted == null || highlighted === i ? 1 : 0.3);
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <BarChart
          data={data}
          margin={{ top: 8, right: 8, left: -24, bottom: 0 }}
          onMouseMove={(state) => {
            const i = state?.activeTooltipIndex;
            onActive?.(i == null || i === "" ? null : n - 1 - Number(i));
          }}
          onMouseLeave={() => onActive?.(null)}
        >
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis
            dataKey="name"
            tick={{ fontSize: 11, fill: "var(--muted)" }}
            interval={0}
            angle={-35}
            textAnchor="end"
            height={56}
          />
          <YAxis tick={{ fontSize: 11, fill: "var(--muted)" }} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: "var(--border)", fillOpacity: 0.5 }}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12 }}
            formatter={(v) => (typeof v === "number" ? v.toFixed(2) : v)}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="xG" fill="var(--home)" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={`xg-${i}-${d.name}`} fillOpacity={opacity(i)} />
            ))}
          </Bar>
          <Bar dataKey="xGA" fill="var(--away)" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={`xga-${i}-${d.name}`} fillOpacity={opacity(i)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
