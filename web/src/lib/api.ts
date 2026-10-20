// Zugriff auf die Python-API (fussballdb serve). Nur serverseitig verwenden.

const BASE = process.env.FUSSBALL_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, cache: "no-store" });
  } catch {
    throw new ApiError(`Python-API unter ${BASE} nicht erreichbar. Läuft "uv run fussballdb serve"?`, 503);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `API-Fehler ${res.status}`, res.status);
  }
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]),
  ).toString();

export type Upcoming = {
  matchday: number;
  kickoff: string;
  home: string;
  away: string;
  p_home: number | null;
  p_draw: number | null;
  p_away: number | null;
  exp_home_goals: number | null;
  exp_away_goals: number | null;
  prediction_from: string | null;
};

export type TableRow = {
  name: string;
  sp: number;
  pkt: number;
  tore: number;
  gegentore: number;
  xg: number;
  xga: number;
  xpts: number;
};

export type FormGame = {
  datum: string;
  saison: string;
  matchday: number;
  ort: "H" | "A";
  gegner: string;
  tore: number;
  gegentore: number;
  xg: number | null;
  xga: number | null;
  shots: number | null;
  shots_against: number | null;
  shots_on_target: number | null;
  big_chances: number | null;
  big_chances_against: number | null;
  ppda: number | null;
  xpts: number | null;
};

export type TeamForm = {
  team_id: number;
  zusammenfassung: Record<string, number>;
  spiele: FormGame[];
};

export type Absence = {
  player_id: number | null;
  player_name: string;
  kind: "injury" | "suspension";
  reason: string | null;
  expected_return: string | null;
  market_value: string | null;
  minutenanteil_letzte_spiele?: number;
  anteil_xg_xa?: number;
  stammspieler?: boolean;
};

export type SideAbsences = {
  fehlende_stammspieler: string[];
  fehlender_offensivanteil: number;
  tor_faktor_angriff: number;
  gegentor_faktor: number;
};

export type Prediction = {
  spiel: { id: number; kickoff: string; matchday: number } | string;
  p_home: number;
  p_draw: number;
  p_away: number;
  exp_goals: [number, number];
  p_over25: number;
  p_btts: number;
  wahrscheinlichste_ergebnisse: string[];
  teilmodelle: {
    dixon_coles: { p_home: number; p_draw: number; p_away: number };
    elo: { p_home: number; p_draw: number; p_away: number; elo_home: number; elo_away: number };
  };
  ausfaelle: { home: SideAbsences; away: SideAbsences };
  marktquoten: { bookmaker: string; is_closing: boolean; home: number; draw: number; away: number }[];
  tipp: string;
  begruendung: string[];
};

export type H2H = {
  datum: string;
  heim: string;
  gast: string;
  home_goals: number;
  away_goals: number;
  xg_heim: number | null;
  xg_gast: number | null;
};

export const getUpcoming = (limit = 9) => api<Upcoming[]>(`/upcoming?${q({ limit })}`);
export const getTable = (season?: number) => api<TableRow[]>(`/table?${q({ season })}`);
export const getTeams = () => api<{ id: number; name: string }[]>("/teams");
export const getForm = (team: string, lastN = 8) =>
  api<TeamForm>(`/teams/${encodeURIComponent(team)}/form?${q({ last_n: lastN })}`);
export const getAbsences = (team: string) => api<Absence[]>(`/teams/${encodeURIComponent(team)}/absences`);
export const getH2H = (teamA: string, teamB: string) => api<H2H[]>(`/h2h?${q({ team_a: teamA, team_b: teamB })}`);
export const getPrediction = (home: string, away: string) => api<Prediction>(`/predict?${q({ home, away })}`);
export const runSql = (query: string) =>
  api<Record<string, unknown>[]>("/sql", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query }),
  });

/** Lädt Daten und liefert entweder das Ergebnis oder eine lesbare Fehlermeldung (für Seiten). */
export async function load<T>(fn: () => Promise<T>): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  try {
    return { ok: true, data: await fn() };
  } catch (e) {
    return { ok: false, error: e instanceof ApiError ? e.message : "Fehler beim Laden" };
  }
}

export type Season = { start_year: number; label: string; matchdays: number; current_matchday: number; finished: boolean };

export type MatchdayGame = {
  id: number;
  kickoff: string;
  wochentag: string;
  home: string;
  away: string;
  home_goals: number | null;
  away_goals: number | null;
  finished: boolean;
  home_xg: number | null;
  away_xg: number | null;
  p_home: number | null;
  p_draw: number | null;
  p_away: number | null;
  exp_home_goals: number | null;
  exp_away_goals: number | null;
  tip_home: number | null;
  tip_away: number | null;
  basis: "live" | "rueckblick" | null;
  as_of: string | null;
  missing_home: string | null;
  missing_away: string | null;
  points: number | null;
  explanation: string[];
};

export type Bilanz = { spiele: number; punkte: number; tendenz: number; exakt: number };

export type Punkteregel = { sieg_tendenz: number; sieg_tordifferenz: number; exakt: number; remis_tendenz: number };

export type Matchday = {
  season: number;
  matchday: number;
  games: MatchdayGame[];
  summary: Bilanz;
  season_summary: Bilanz;
  punkteregel: Punkteregel;
};

export const getSeasons = () => api<Season[]>("/seasons");
export const getMatchday = (season: number, matchday: number) => api<Matchday>(`/matchday/${season}/${matchday}`);

export type KickbaseRow = {
  player_id: number;
  name: string;
  team_id: number;
  team_name: string;
  position: "TW" | "ABW" | "MF" | "ST";
  spiele: number;
  einsatz: number;
  minuten: number;
  tore: number;
  vorlagen: number;
  torbeteiligung: number;
  zu_null: number | null;
  gelb: number;
  ausfall: "injury" | "suspension" | null;
  aufstellung: "start" | "alternative" | "bank" | null;
  gegner: string[];
  heim: boolean[];
  saison_tore: number;
  saison_vorlagen: number;
  kb_punkte: number | null;
  marktwert: number | null;
  trend_7t: number | null;
  punkte_pro_mio: number | null;
  avg_points: number | null;
  markt_preis: number | null;
  markt_ablauf: number | null;
  im_kader: boolean;
};

export const getKickbaseProjections = (matchdays: number) =>
  api<KickbaseRow[]>(`/kickbase/projections?matchdays=${matchdays}`);
