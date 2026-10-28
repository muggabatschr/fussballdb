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
  // Modell-Platz: Platz nach den Punkten, die die Prognosen vor den gespielten Spielen erwarten ließen
  modell_pkt?: number;
  modell_platz?: number;
  platz_diff?: number; // > 0: steht so viele Plätze besser als erwartet
  // Hochrechnung zum Saisonende (nur solange Spiele offen sind)
  prognose_platz?: number;
  erw_punkte?: number;
  p_meister?: number;
  p_top4?: number;
  p_abstieg?: number;
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
  farbe?: TeamColor | null; // Vereinsfarbe laut FotMob
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
  heim?: string;
  gast?: string;
  torschuetzen_heim?: Scorer[];
  torschuetzen_gast?: Scorer[];
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
  // Pokal: Chance aufs Weiterkommen (mit Verlängerung und Elfmeterschießen) und Anteile der Wege dorthin
  weiter?: { home: number; away: number; verlaengerung: number; elfmeterschiessen: number };
  season?: number; // Startjahr (Bundesliga-Spieltag und Europa-Modell)
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
  tv?: Partial<Record<"DE" | "AT", string[]>>;
  torschuetzen?: { home: Scorer[]; away: Scorer[] };
  ort?: Venue | null;
};

/** Spielort laut FotMob (Name und Kapazität wie am Spieltag) mit Wetter von Open-Meteo zur Spielzeit. */
export type Venue = {
  stadion: string;
  stadt: string | null;
  land: string | null;
  kapazitaet: number | null;
  wetter: {
    art: "vorhersage" | "gemessen";
    temp_c: number | null;
    regen_mm: number | null;
    regen_pct: number | null;
    wind_kmh: number | null;
    code: number | null;
  } | null;
  // nur bei offenen Spielen: Google Maps mit ÖPNV, Ankunft eine Stunde vor dem Anpfiff (Ortszeit am Stadion)
  anreise?: { ankunft: string; url: string; url_vorlage: string; url_ohne_zeit: string } | null;
};

export type Scorer = { name: string; p: number; tore: number };

export type Bilanz = { spiele: number; punkte: number; tendenz: number; exakt: number };

export type Punkteregel = { sieg_tendenz: number; sieg_tordifferenz: number; exakt: number; remis_tendenz: number };

export type Matchday = {
  season: number;
  matchday: number;
  games: MatchdayGame[];
  summary: Bilanz;
  season_summary: Bilanz;
  punkteregel: Punkteregel;
  tipprunde?: TipRoundInfo;
};

export const getSeasons = () => api<Season[]>("/seasons");

export type ClRoundInfo = { round_no: number; round_name: string; spiele: number; finished: boolean; start: string };
export type ClSeason = { season: number; label: string; rounds: ClRoundInfo[]; current_round: number };
export type ClGame = MatchdayGame & {
  round_name: string;
  neutral: boolean;
  elo_home: number | null;
  elo_away: number | null;
  value_home: number | null;
  value_away: number | null;
};
export type ClRound = {
  season: number;
  round_no: number;
  round_name: string;
  games: ClGame[];
  summary: Bilanz;
  season_summary: Bilanz;
  punkteregel: Punkteregel;
};

export const getClRounds = () => api<ClSeason[]>("/cl/rounds");

export type ClTableRow = {
  name: string;
  sp: number;
  pkt: number;
  tore: number;
  gegentore: number;
  platz: number;
  modell_pkt?: number;
  modell_platz?: number;
  platz_diff?: number;
  prognose_platz?: number;
  erw_punkte?: number;
  p_achtelfinale?: number;
  p_playoffs?: number;
  p_aus?: number;
};
export type TableZone = { key: string; label: string; von: number; bis: number };
export type ClTable = { season: number; label: string; rows: ClTableRow[]; zonen?: TableZone[]; wettbewerb?: string };
export const getClTable = (season: number) => api<ClTable>(`/cl/table/${season}`);
export const getClRound = (season: number, round: number) => api<ClRound>(`/cl/round/${season}/${round}`);
export const getCompRounds = (comp: string) => api<ClSeason[]>(`/eu/${comp}/rounds`);
export const getCompRound = (comp: string, season: number, round: number) =>
  api<ClRound>(`/eu/${comp}/round/${season}/${round}`);
export const getCompTable = (comp: string, season: number) => api<ClTable>(`/eu/${comp}/table/${season}`);
export const getMatchday = (season: number, matchday: number, runde?: string) =>
  api<Matchday>(`/matchday/${season}/${matchday}?${q({ runde })}`);

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

export type LineupPlayer = { name: string; position: "TW" | "ABW" | "MF" | "ST"; team_name: string; kb_punkte: number; einsatz: number; gegner: string[] };
export type KickbaseLineup = {
  formation: string | null;
  punkte: number | null;
  elf: LineupPlayer[];
  bank: LineupPlayer[];
  ausfaelle: { name: string; position: string; grund: string }[];
  hinweis?: string;
};
export const getKickbaseLineup = () => api<KickbaseLineup>("/kickbase/aufstellung");

export type KickbaseStatus = {
  angemeldet: boolean;
  abgelaufen?: boolean;
  gueltig_bis?: string | null;
  ligen?: { id: string; name: string }[];
  liga?: string | null;
};
export const getKickbaseStatus = () => api<KickbaseStatus>("/kickbase/status");

export type DetailFormGame = {
  id: number;
  kickoff: string;
  ort: "H" | "A";
  gegner: string;
  tore: number;
  gegentore: number;
  xg: number | null;
  xga: number | null;
  wettbewerb?: string; // nur Europa-Modell: Liga oder Pokal des Spiels
  round_name?: string | null;
};

export type DetailH2H = {
  id: number;
  kickoff: string;
  saison?: string;
  wettbewerb?: string;
  home: string;
  away: string;
  home_goals: number;
  away_goals: number;
  home_xg: number | null;
  away_xg: number | null;
};

export type H2HSummary = { spiele: number; siege_heim: number; remis: number; siege_gast: number; tore_heim: number; tore_gast: number };

export type MatchStats = {
  goals: number;
  xg: number | null;
  shots: number | null;
  shots_on_target: number | null;
  big_chances: number | null;
  corners: number | null;
  fouls: number | null;
  yellow_cards: number | null;
  red_cards: number | null;
  ppda: number | null;
  xpts: number | null;
};

export type DetailAbsence = Absence & { value_share?: number | null };

type Sides<T> = { home: T; away: T };

/** Spieldetail (Bundesliga: /match/{id}, sonst /eu/{comp}/match/{id}). Felder, die es nur in einem der beiden
 * Modelle gibt, sind optional. */
export type MatchDetail = {
  wettbewerb: string;
  game: ClGame & { season: number; season_label?: string; matchday?: number; round_no?: number };
  punkteregel: Punkteregel;
  tipprunde?: TipRoundInfo;
  form: Sides<DetailFormGame[]>;
  h2h: DetailH2H[];
  h2h_summary: H2HSummary;
  tabelle:
    | (Sides<(Partial<TableRow> & Partial<ClTableRow> & { name: string; platz: number }) | null> & {
        stand: string;
        zonen?: TableZone[];
      })
    | null;
  ausfaelle: Sides<DetailAbsence[]> | null;
  aufstellung?: Sides<{ reihe: number | null; name: string }[]> | null;
  statistik?: Sides<MatchStats> | null;
  quoten?: { bookmaker: string; is_closing: boolean; p_home: number; p_draw: number; p_away: number }[];
  kaderwert?: Sides<number | null>;
  bericht?: string | null; // Spielbericht aus den Daten (Bundesliga, gespielt)
  spielfeld?: MatchPage | null; // Aufstellung und Momentum laut FotMob
  farben?: Sides<TeamColor | null> | null; // Teamfarben laut FotMob
};

export type TeamColor = { hell: string; dunkel: string; schrift_hell?: string | null; schrift_dunkel?: string | null };

/** Spieler auf dem Feld laut FotMob: x/y waagerecht (x 0 = eigenes Tor, 1 = Mittellinie), vx/vy senkrecht. */
export type PitchPlayer = {
  name: string;
  voller_name: string;
  nummer: string | null;
  note: number | null;
  tore: number;
  vorlagen: number;
  eigentore: number;
  gelb: boolean;
  rot: boolean;
  elfmeter_verschossen: number;
  elfmeter_gehalten: number;
  raus: number | null;
  rein: number | null;
  spieler_des_spiels?: boolean;
  kapitaen?: boolean;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
};
export type PitchTeam = {
  name: string;
  formation: string | null;
  note: number | null;
  trainer: string | null;
  startelf: PitchPlayer[];
  bank: PitchPlayer[];
};
export type MatchEvent = {
  minute: number;
  nachspiel: number | null;
  pos: number;
  heim: boolean;
  art: "tor" | "eigentor" | "rot" | "gelbrot" | "elfmeter_vergeben";
  spieler: string;
  stand?: [number, number];
};
export type MatchPage = {
  art: "offiziell" | "voraussichtlich";
  aufstellung: Sides<PitchTeam> | null;
  momentum: [number, number][] | null; // Minute, Wert -100 bis 100 (> 0 = Heimteam drückt)
  ereignisse: MatchEvent[];
};

export const getMatchDetail = (id: number, runde?: string) => api<MatchDetail>(`/match/${id}?${q({ runde })}`);
export const getCompMatchDetail = (comp: string, id: number) => api<MatchDetail>(`/eu/${comp}/match/${id}`);

/** Kicktipp-Tipprunde mit Punkteregel (Tipps und Punkte werden je Runde gerechnet). */
export type TipRound = {
  slug: string;
  name: string;
  url: string | null;
  lead_minutes: number | null;
  bonus_points: number | null;
  punkteregel: Punkteregel;
  standard: boolean;
};
export type TipRoundInfo = Pick<TipRound, "slug" | "name" | "url" | "lead_minutes" | "bonus_points">;

export type BonusQuestion = {
  termin: string;
  frage: string;
  kurz: string;
  antworten: string[];
  prognose: { team: string; p: number }[] | null; // mit dem Wissen zum Tippschluss (stichtag)
  heute: { team: string; p: number }[] | null; // Stand heute zum Vergleich
  stichtag: string | null;
  hinweis: string | null;
};

export type ReportHit = {
  match_id: number;
  datum: string;
  saison: number;
  spieltag: number;
  bericht: string;
  relevanz: number;
  suche: string;
  link: string;
};
export const searchReports = (query: string, team?: string, saison?: number, limit = 8, neueste = false) =>
  api<ReportHit[]>(`/reports/search?${q({ q: query, team, saison, limit, neueste: neueste ? "true" : undefined })}`);

export const getTipRounds = () => api<TipRound[]>("/tipprunden");
export const getTipBonus = (slug: string) =>
  api<{ tipprunde: TipRoundInfo; fragen: BonusQuestion[] }>(`/tipprunden/${encodeURIComponent(slug)}/extratipps`);
