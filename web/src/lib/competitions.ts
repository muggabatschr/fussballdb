/** Wettbewerbe mit eigener Rundenansicht (Prognosen aus dem Europa-Modell). */
export type CompCode = "CL" | "D2" | "DFB";

export type Competition = {
  code: CompCode;
  base: string; // URL-Präfix
  short: string; // für Überschriften und Tabs
  name: string;
  table: string | null; // Linktext zur Tabelle, null = keine Tabelle (Pokal)
  note: string; // Erklärung unter der Bilanz
};

export const COMPETITIONS: Record<CompCode, Competition> = {
  CL: {
    code: "CL",
    base: "/cl",
    short: "CL",
    name: "Champions League",
    table: "Tabelle Ligaphase",
    note:
      "Grundlage: europaweites xG-Modell (70 %) und Elo (30 %) aus Liga- und Europapokalspielen, Kaderwert als " +
      "Startwert. Bei K.-o.-Spielen zählt das Endergebnis inklusive Verlängerung.",
  },
  D2: {
    code: "D2",
    base: "/2bl",
    short: "2. Liga",
    name: "2. Bundesliga",
    table: "Tabelle",
    note:
      "Grundlage: dasselbe Modell wie für die CL (Elo und Dixon-Coles über Tore, Kaderwert als Startwert). " +
      "Für die 2. Bundesliga gibt es kein xG, sie ist deshalb gröber als die Bundesliga-Prognose.",
  },
  DFB: {
    code: "DFB",
    base: "/pokal",
    short: "Pokal",
    name: "DFB-Pokal",
    table: null,
    note:
      "Grundlage: Elo und Dixon-Coles über Bundesliga, 2. und 3. Liga, Kaderwert als Startwert. Amateurteams ohne " +
      "Liga- und Kaderdaten starten deutlich schwächer. Gewertet wird das Endergebnis inklusive Verlängerung.",
  },
};
