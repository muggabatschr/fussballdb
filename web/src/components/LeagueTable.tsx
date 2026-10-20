import type { TableRow } from "@/lib/api";
import { num } from "@/lib/format";
import { TeamName } from "./TeamName";

export function LeagueTable({ rows }: { rows: TableRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm tabular [&_td]:whitespace-nowrap">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Team</th>
            <th className="px-3 py-2 text-right">Sp</th>
            <th className="px-3 py-2 text-right">Tore</th>
            <th className="px-3 py-2 text-right">Pkt</th>
            <th className="px-3 py-2 text-right" title="Expected Goals">xG</th>
            <th className="px-3 py-2 text-right" title="Expected Goals gegen">xGA</th>
            <th className="px-3 py-2 text-right" title="Erwartete Punkte laut xG">xPts</th>
            <th className="px-3 py-2 text-right" title="Punkte minus erwartete Punkte">Pkt − xPts</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const diff = r.pkt - r.xpts;
            return (
              <tr key={r.name} className="border-b border-border last:border-0">
                <td className="px-3 py-2 text-muted">{i + 1}</td>
                <td className="px-3 py-2">
                  <TeamName name={r.name} />
                </td>
                <td className="px-3 py-2 text-right">{r.sp}</td>
                <td className="px-3 py-2 text-right">
                  {r.tore}:{r.gegentore}
                </td>
                <td className="px-3 py-2 text-right font-semibold">{r.pkt}</td>
                <td className="px-3 py-2 text-right">{num(r.xg, 1)}</td>
                <td className="px-3 py-2 text-right">{num(r.xga, 1)}</td>
                <td className="px-3 py-2 text-right">{num(r.xpts, 1)}</td>
                <td className={`px-3 py-2 text-right ${diff > 0 ? "text-home" : "text-away"}`}>
                  {diff > 0 ? "+" : ""}
                  {num(diff, 1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
