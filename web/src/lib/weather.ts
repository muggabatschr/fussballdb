// Wetter-Codes von Open-Meteo (WMO) in kurze deutsche Beschreibungen
const CODES: [number[], string][] = [
  [[0], "klar"],
  [[1], "überwiegend klar"],
  [[2], "teils bewölkt"],
  [[3], "bedeckt"],
  [[45, 48], "Nebel"],
  [[51], "leichter Nieselregen"],
  [[53, 55], "Nieselregen"],
  [[56, 57], "gefrierender Nieselregen"],
  [[61], "leichter Regen"],
  [[63], "Regen"],
  [[65], "starker Regen"],
  [[66, 67], "gefrierender Regen"],
  [[71], "leichter Schneefall"],
  [[73], "Schneefall"],
  [[75], "starker Schneefall"],
  [[77], "Schneegriesel"],
  [[80], "leichte Regenschauer"],
  [[81], "Regenschauer"],
  [[82], "heftige Regenschauer"],
  [[85, 86], "Schneeschauer"],
  [[95], "Gewitter"],
  [[96, 99], "Gewitter mit Hagel"],
];

export const weatherText = (code: number | null) =>
  code == null ? null : (CODES.find(([codes]) => codes.includes(code))?.[1] ?? null);
