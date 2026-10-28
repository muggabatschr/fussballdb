// Dünne Hüllen um die Python-API. Die Logik (Daten, Prognosemodell) liegt komplett in Python.
import { type InferUITools, type ToolSet, type UIDataTypes, type UIMessage, tool } from "ai";
import { z } from "zod";
import {
  getAbsences,
  getCompRound,
  getCompRounds,
  getForm,
  getH2H,
  getMatchday,
  getPrediction,
  getSeasons,
  getTable,
  getUpcoming,
  runSql,
  searchNews,
  searchReports,
} from "@/lib/api";
import { COMPETITIONS } from "@/lib/competitions";
import type { TipSheetProps } from "@/components/TipSheet";
import { selectedTipRound } from "@/lib/tipround";

/** Tipp-Zettel wie auf /tipps: Bundesliga-Spieltag oder Runde von 2. Liga, CL, Pokal, Brasilien; ohne Angabe die aktuelle. */
async function tipSheet(comp: "BL" | "D2" | "CL" | "DFB" | "BRA", season?: number, round?: number, tipRound?: string): Promise<TipSheetProps> {
  if (comp === "BL") {
    const seasons = await getSeasons();
    const s = seasons.find((x) => x.start_year === season) ?? seasons[0];
    // Tipprunde: genannt, sonst die im Browser gewählte (Cookie), sonst die Standardrunde
    const d = await getMatchday(s.start_year, round ?? s.current_matchday, tipRound ?? (await selectedTipRound()));
    return {
      title: `${d.matchday}. Spieltag`,
      subtitle: `Bundesliga ${s.label}${d.tipprunde?.name ? ` · ${d.tipprunde.name}` : ""}`,
      games: d.games,
      backHref: `/tipps/${d.season}/${d.matchday}`,
      backLabel: "öffnen",
      fileName: `tipps-bundesliga-${d.season}-${d.matchday}.png`,
    };
  }
  const c = COMPETITIONS[comp];
  const seasons = await getCompRounds(comp);
  const s = seasons.find((x) => x.season === season) ?? seasons[0];
  const d = await getCompRound(comp, s.season, round ?? s.current_round);
  return {
    title: d.round_name,
    subtitle: `${c.name} ${s.label}`,
    games: d.games,
    backHref: `${c.base}/tipps/${d.season}/${d.round_no}`,
    backLabel: "öffnen",
    fileName: `tipps-${c.base.slice(1)}-${d.season}-${d.round_no}.png`,
  };
}

const team = z.string().describe("Teamname, auch umgangssprachlich (z. B. BVB, Gladbach, Bayern)");

export const tools = {
  get_upcoming_matches: tool({
    description: "Die nächsten Bundesliga-Spiele mit gespeicherter Modellprognose (1/X/2, erwartete Tore).",
    inputSchema: z.object({ limit: z.number().int().min(1).max(50).optional().describe("Anzahl, Standard 9") }),
    execute: ({ limit }) => getUpcoming(limit ?? 9),
  }),
  get_team_form: tool({
    description:
      "Letzte Spiele eines Teams mit Ergebnis, xG, Schüssen, Großchancen, PPDA sowie Durchschnittswerte. " +
      "Achtung: die letzten N Spiele können in die Vorsaison reichen (Feld saison).",
    inputSchema: z.object({ team, last_n: z.number().int().min(1).max(40).optional().describe("Anzahl Spiele, Standard 8") }),
    execute: async ({ team, last_n }) => ({ team, ...(await getForm(team, last_n ?? 8)) }),
  }),
  get_head_to_head: tool({
    description: "Direkte Bundesliga-Duelle zweier Teams seit 1993/94 mit Ergebnis, xG ab 2014/15.",
    inputSchema: z.object({ team_a: team, team_b: team }),
    execute: ({ team_a, team_b }) => getH2H(team_a, team_b),
  }),
  predict_match: tool({
    description:
      "Modellprognose (Dixon-Coles auf xG mit Form + Elo, Kaderwert als Startstärke, korrigiert um die aktuelle " +
      "Verletztenliste) für eine Paarung: Wahrscheinlichkeiten Heimsieg/Remis/Auswärtssieg, erwartete Tore, " +
      "wahrscheinlichste Ergebnisse, Über 2,5, beide treffen, Ausfälle mit Einfluss, Marktquoten.",
    inputSchema: z.object({ home: team.describe("Heimteam"), away: team.describe("Gastteam") }),
    execute: async ({ home, away }) => {
      const p = await getPrediction(home, away);
      // offizielle Namen aus der Datenbank, damit die Karte Wappen und Kurznamen findet ("BVB" -> Borussia Dortmund)
      return { ...p, home: p.heim ?? home, away: p.gast ?? away };
    },
  }),
  get_absences: tool({
    description: "Aktuelle Ausfälle (Verletzungen, Sperren) eines Teams mit Bedeutung des Spielers.",
    inputSchema: z.object({ team }),
    execute: async ({ team }) => ({ team, ausfaelle: await getAbsences(team) }),
  }),
  get_table: tool({
    description:
      "Tabelle einer Saison mit Punkten, Toren, xG, xGA, xPts und Modell-Platz (platz_diff > 0 = steht besser als " +
      "erwartet), dazu die Hochrechnung zum Saisonende (prognose_platz, erw_punkte, p_meister, p_top4, p_abstieg in %).",
    inputSchema: z.object({
      season: z.number().int().optional().describe("Startjahr ab 1993 (vor 2014 ohne xG), z. B. 2026; Standard aktuelle Saison"),
    }),
    execute: ({ season }) => getTable(season),
  }),
  get_tip_sheet: tool({
    description:
      "Tipp-Zettel: alle Tipps eines Spieltags bzw. einer Runde (Ergebnis mit den meisten erwarteten Tipp-Punkten). " +
      "Nutzen bei Fragen nach Tipp-Zettel, Tippzettel oder allen Tipps eines Spieltags. Bundesliga-Tipps richten " +
      "sich nach der Punkteregel der Tipprunde (Kicktipp). Der Nutzer sieht den Zettel " +
      "als Box mit Wappen und kann ihn als Bild oder Text teilen.",
    inputSchema: z.object({
      wettbewerb: z
        .enum(["BL", "D2", "CL", "DFB", "BRA"])
        .optional()
        .describe("BL = Bundesliga (Standard), D2 = 2. Bundesliga, CL = Champions League, DFB = DFB-Pokal, BRA = brasilianische Série A"),
      saison: z.number().int().optional().describe("Startjahr, z. B. 2026; Standard aktuelle Saison"),
      spieltag: z.number().int().optional().describe("Spieltag bzw. Runde; Standard der nächste offene"),
      tipprunde: z
        .string()
        .optional()
        .describe("Kicktipp-Tipprunde (Kurzname, z. B. waschndalos), nur Bundesliga; Standard die gewählte Runde"),
    }),
    execute: async ({ wettbewerb, saison, spieltag, tipprunde }) => {
      const sheet = await tipSheet(wettbewerb ?? "BL", saison, spieltag, tipprunde);
      // nur was Box und Modell brauchen
      return {
        ...sheet,
        games: sheet.games.map(({ id, kickoff, home, away, tip_home, tip_away }) => ({ id, kickoff, home, away, tip_home, tip_away })),
      };
    },
  }),
  search_reports: tool({
    description:
      "Spielberichte der Bundesliga ab 2014/15 im Zeitungsstil durchsuchen (Tore mit Minute, Schütze, Vorlage, Art; " +
      "Pfosten und vergebene Chancen; Formation; Spieler des Spiels; Tabelle und Serien; Statistik; " +
      "Einordnung; Stichworte wie Comeback, spätes Siegtor, Platzverweis, Überraschung). Für Fragen zu " +
      "Spielverläufen und Zusammenfassungen. Ohne frage die jüngsten Spiele des Teams/der Saison.",
    inputSchema: z.object({
      frage: z.string().optional().describe("Wonach gesucht wird, z. B. 'Sieg nach Rückstand' oder 'Rote Karte'"),
      team: team.optional(),
      saison: z.number().int().optional().describe("Startjahr, z. B. 2025 für 2025/26"),
      anzahl: z.number().int().min(1).max(12).optional().describe("Anzahl Berichte, Standard 6"),
      neueste_zuerst: z.boolean().optional().describe("true bei 'wann zuletzt …': die jüngsten Treffer"),
    }),
    execute: ({ frage, team, saison, anzahl, neueste_zuerst }) =>
      searchReports(frage ?? "", team, saison, anzahl ?? 6, neueste_zuerst ?? false),
  }),
  search_news: tool({
    description:
      "Aktuelle Meldungen über Bundesliga-Vereine aus der Presse (letzte Tage): Überschrift, Quelle, Datum, Link, " +
      "art = lokal (Zeitung der Region) oder verein. Für Fragen wie 'was schreibt die Lokalpresse über …', Stimmung, " +
      "Trainerstimmen, Verletzungsgerüchte. Nur Überschriften, keine Artikeltexte: nichts dazuerfinden, Links nennen.",
    inputSchema: z.object({
      frage: z.string().optional().describe("Wonach gesucht wird, z. B. 'Verletzung' oder 'Trainer'"),
      team: team.optional(),
      tage: z.number().int().min(1).max(60).optional().describe("Zeitraum in Tagen, Standard 7"),
      nur_lokal: z.boolean().optional().describe("true = nur Lokalzeitungen und Vereinsseiten"),
    }),
    execute: ({ frage, team, tage, nur_lokal }) => searchNews(frage ?? "", team, tage ?? 7, nur_lokal ?? false),
  }),
  run_sql: tool({
    description:
      "Lesende SQL-Abfrage (nur SELECT/WITH, max. 200 Zeilen) für Fragen, die die anderen Werkzeuge nicht abdecken. " +
      "Tabellen: match, match_team_stats, shot, odds, player, player_match, player_absence, elo_rating, prediction, team, season, " +
      "news_item (Meldungen: team_id, title, source, kind, published_at, link).",
    inputSchema: z.object({ query: z.string() }),
    execute: ({ query }) => runSql(query),
  }),
} satisfies ToolSet;

export type ChatTools = InferUITools<typeof tools>;
export type ChatMessage = UIMessage<never, UIDataTypes, ChatTools>;
