// Dünne Hüllen um die Python-API. Die Logik (Daten, Prognosemodell) liegt komplett in Python.
import { type InferUITools, type ToolSet, type UIDataTypes, type UIMessage, tool } from "ai";
import { z } from "zod";
import { getAbsences, getForm, getH2H, getPrediction, getTable, getUpcoming, runSql } from "@/lib/api";

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
    description: "Direkte Duelle zweier Teams in der Datenbank mit Ergebnis und xG.",
    inputSchema: z.object({ team_a: team, team_b: team }),
    execute: ({ team_a, team_b }) => getH2H(team_a, team_b),
  }),
  predict_match: tool({
    description:
      "Modellprognose (Dixon-Coles auf xG mit Form + Elo, Kaderwert als Startstärke, korrigiert um die aktuelle " +
      "Verletztenliste) für eine Paarung: Wahrscheinlichkeiten Heimsieg/Remis/Auswärtssieg, erwartete Tore, " +
      "wahrscheinlichste Ergebnisse, Über 2,5, beide treffen, Ausfälle mit Einfluss, Marktquoten.",
    inputSchema: z.object({ home: team.describe("Heimteam"), away: team.describe("Gastteam") }),
    execute: async ({ home, away }) => ({ home, away, ...(await getPrediction(home, away)) }),
  }),
  get_absences: tool({
    description: "Aktuelle Ausfälle (Verletzungen, Sperren) eines Teams mit Bedeutung des Spielers.",
    inputSchema: z.object({ team }),
    execute: async ({ team }) => ({ team, ausfaelle: await getAbsences(team) }),
  }),
  get_table: tool({
    description: "Tabelle einer Saison mit Punkten, Toren, xG, xGA und xPts.",
    inputSchema: z.object({ season: z.number().int().optional().describe("Startjahr, z. B. 2026; Standard aktuelle Saison") }),
    execute: ({ season }) => getTable(season),
  }),
  run_sql: tool({
    description:
      "Lesende SQL-Abfrage (nur SELECT/WITH, max. 200 Zeilen) für Fragen, die die anderen Werkzeuge nicht abdecken. " +
      "Tabellen: match, match_team_stats, shot, odds, player, player_match, player_absence, elo_rating, prediction, team, season.",
    inputSchema: z.object({ query: z.string() }),
    execute: ({ query }) => runSql(query),
  }),
} satisfies ToolSet;

export type ChatTools = InferUITools<typeof tools>;
export type ChatMessage = UIMessage<never, UIDataTypes, ChatTools>;
