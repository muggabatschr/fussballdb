/** Wettbewerbe mit eigener Rundenansicht (Prognosen aus dem Europa-Modell). */
export type CompCode = "CL" | "D2" | "DFB" | "BRA";

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
      "Grundlage: dasselbe Modell wie für die CL, xG-Modell mit Form (70 %) und Elo (30 %), Kaderwert als " +
      "Startwert; xG der 2. Liga von FotMob ab 2022/23. Ohne Verletzte und Kader gröber als die Bundesliga-Prognose.",
  },
  DFB: {
    code: "DFB",
    base: "/pokal",
    short: "Pokal",
    name: "DFB-Pokal",
    table: null,
    note:
      "Grundlage: Elo und Dixon-Coles über Bundesliga, 2. und 3. Liga, Kaderwert als Startwert. Amateurteams ohne " +
      "Liga- und Kaderdaten starten deutlich schwächer. Prognose, Tipp und Punkte gelten für das Ergebnis nach 90 " +
      "Minuten; „Weiter“ ist die Chance aufs Weiterkommen mit Verlängerung und Elfmeterschießen.",
  },
  BRA: {
    code: "BRA",
    base: "/brasilien",
    short: "Brasilien",
    name: "Série A (Brasilien)",
    table: "Tabelle",
    note:
      "Grundlage: eigenes Modell nur aus brasilianischen Spielen (Elo seit 2012, Dixon-Coles auf xG von FotMob ab " +
      "2023, Kaderwert als Startwert), getrennt von Europa. Die Liga ist schwerer vorherzusagen als die " +
      "Bundesliga: starker Heimvorteil, viele Remis, ausgeglichene Teams.",
  },
};

/** Saisonbezeichnung: Brasilien spielt im Kalenderjahr ("2026"), sonst "2026/27". */
export const seasonLabel = (code: CompCode, season: number) =>
  code === "BRA" ? String(season) : `${season}/${String((season + 1) % 100).padStart(2, "0")}`;
