"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { FormGame } from "@/lib/api";

export function XgChart({ games }: { games: FormGame[] }) {
  const data = [...games].reverse().map((g) => ({
    name: `${g.ort === "H" ? "" : "@"}${g.gegner.split(" ").slice(-1)[0]}`,
    xG: g.xg,
    xGA: g.xga,
  }));
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
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
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12 }}
            formatter={(v) => (typeof v === "number" ? v.toFixed(2) : v)}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="xG" fill="var(--home)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="xGA" fill="var(--away)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
