import type { TeamColor } from "@/lib/api";

/** Färbt alles darin, was die Farben Heim/Gast nutzt (bg-home, fill-away …), in den Teamfarben laut FotMob,
 * für hellen und dunklen Modus getrennt (siehe .team-colors in globals.css). Ohne Farben bleibt der Standard. */
export function TeamColors({
  colors,
  className = "",
  children,
}: {
  colors?: { home: TeamColor | null; away: TeamColor | null } | null;
  className?: string;
  children: React.ReactNode;
}) {
  if (!colors) return <div className={className}>{children}</div>;
  const vars: Record<string, string> = {};
  for (const side of ["home", "away"] as const) {
    const c = colors[side];
    if (!c) continue;
    vars[`--tc-${side}`] = c.hell;
    vars[`--tc-${side}-dark`] = c.dunkel;
    if (c.schrift_hell) vars[`--tc-${side}-fg`] = c.schrift_hell;
    if (c.schrift_dunkel) vars[`--tc-${side}-fg-dark`] = c.schrift_dunkel;
  }
  return (
    <div className={`team-colors ${className}`} style={vars as React.CSSProperties}>
      {children}
    </div>
  );
}
