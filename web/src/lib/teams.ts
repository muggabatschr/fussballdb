import euTeams from "@/lib/eu_teams.json";
import teams from "@/lib/teams.json";

type TeamInfo = { logo: string | null; short: string };
// Bundesliga-Teams haben Vorrang, Europapokal-Teams (Champions League) ergänzen
const map = { ...(euTeams as Record<string, TeamInfo>), ...(teams as Record<string, TeamInfo>) };
const entries = Object.entries(map);

/** Volle Teamnamen auflösen, auch Kurz- oder Teilnamen ("Freiburg", "Bayern"). */
export function resolveTeam(name: string): { name: string; info: TeamInfo } | null {
  if (map[name]) return { name, info: map[name] };
  const q = name.trim().toLowerCase();
  const byShort = entries.find(([, i]) => i.short.toLowerCase() === q);
  if (byShort) return { name: byShort[0], info: byShort[1] };
  const partial = entries.filter(([full]) => full.toLowerCase().includes(q));
  return partial.length === 1 ? { name: partial[0][0], info: partial[0][1] } : null;
}

export const shortName = (name: string) => resolveTeam(name)?.info.short ?? name;
