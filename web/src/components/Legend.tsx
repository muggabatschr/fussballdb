/** Erklärung der Abkürzungen unter einer Tabelle, in einfachen Worten, mit Richtung (mehr/weniger = besser). */
export function Legend({ items }: { items: [string, string][] }) {
  return (
    <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs text-muted sm:grid-cols-2">
      {items.map(([term, text]) => (
        <div key={term} className="flex gap-1.5">
          <dt className="shrink-0 font-semibold text-foreground/80">{term}</dt>
          <dd>{text}</dd>
        </div>
      ))}
    </dl>
  );
}

type Term = [string, string];

// Wiederkehrende Begriffe, damit sie überall gleich erklärt sind
export const TERMS: Record<string, Term> = {
  sp: ["Sp", "Spiele"],
  tore: ["Tore", "geschossene : kassierte Tore"],
  pkt: ["Pkt", "Punkte (mehr = besser)"],
  xg: ["xG", "Expected Goals: wie viele Tore die eigenen Torchancen im Schnitt wert waren, z. B. Elfmeter ≈ 0,76, Schuss aus 25 m ≈ 0,03 (mehr = besser)"],
  xga: ["xGA", "xG des Gegners: so viele Tore hätte man nach den zugelassenen Chancen im Schnitt kassiert (weniger = besser)"],
  xpts: ["xPts", "erwartete Punkte nach den Torchancen beider Teams (mehr = besser)"],
  diff: ["Pkt − xPts", "Plus = mehr Punkte geholt, als die Chancen hergaben (Effizienz oder Glück), Minus = weniger; auf Dauer gleicht sich das meist aus"],
  platz: ["+2 / −1", "neben dem Platz: so viele Plätze besser (+, grün) oder schlechter (−, orange), als die Prognosen vor den Spielen erwarten ließen"],
  modell: ["Modell", "Punkte, die die Prognosen vor den gespielten Spielen im Schnitt erwarten ließen (zum Vergleich mit Pkt)"],
  erwPkt: ["Pkt", "erwartete Punkte am Ende (Durchschnitt aus 10.000 simulierten Verläufen, mehr = besser)"],
  heute: ["heute", "aktueller Tabellenplatz"],
  erg: ["Erg.", "Ergebnis aus Sicht des Teams (S = Sieg, U = Unentschieden, N = Niederlage)"],
  schuesse: ["Schüsse", "eigene Torschüsse (mehr = besser)"],
  grosschancen: ["Großchancen", "Schüsse mit mindestens 30 % Torwahrscheinlichkeit (xG ≥ 0,3), mehr = besser"],
  ppda: ["PPDA", "gegnerische Pässe je eigener Abwehraktion (Tackling, abgefangener Ball, Foul): weniger = mehr Pressing, Bundesliga-Schnitt etwa 13, Bayern etwa 8"],
};

// Kürzel in den Spieltags- und Rundenkacheln
export const TILE_LEGEND: [string, string][] = [
  ["1 · X · 2", "Chance auf Heimsieg, Unentschieden und Auswärtssieg; der Balken zeigt dasselbe in Farbe"],
  ["Tipp", "Ergebnis mit den meisten erwarteten Punkten nach der Punkteregel der Tipprunde"],
  ["P.", "Tipp-Punkte, die der Tipp geholt hat (grün = getroffen, orange = daneben)"],
  ["Erw. Tore", "Torerwartung des Modells für Heim : Gast"],
  ["ggü. xG", "Tore minus xG: Plus = mehr Tore als die Chancen hergaben, Minus = weniger"],
  ["Live / Rückblick", "Live = Prognose mit heutigem Stand; Rückblick = nur mit den Daten vor dem Spieltag gerechnet"],
];
