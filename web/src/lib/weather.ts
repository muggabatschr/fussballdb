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

const RAIN_CODES = [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99];
const SNOW_CODES = [71, 73, 75, 77, 85, 86];

/** Gefühlte Temperatur im Stadion: Windchill (unter 10 °C und ab 5 km/h Wind) und 2 °C Abzug, weil man
 * 90 Minuten sitzt oder steht. */
export function feltTemperature(temp: number, windKmh: number | null): number {
  const v = windKmh ?? 0;
  const chill =
    temp <= 10 && v >= 5 ? 13.12 + 0.6215 * temp - 11.37 * v ** 0.16 + 0.3965 * temp * v ** 0.16 : temp;
  return chill - 2;
}

type Forecast = { temp_c: number | null; regen_pct: number | null; wind_kmh: number | null; code: number | null };

/** Kleidungsempfehlung für Zuschauer aus der Vorhersage zur Spielzeit: Schichten nach gefühlter Temperatur,
 * dazu Regen- und Windschutz, bei Hitze Sonnenschutz. Schirme sind in den meisten Stadien verboten. */
export function clothingAdvice(w: Forecast): string | null {
  if (w.temp_c == null) return null;
  const felt = feltTemperature(w.temp_c, w.wind_kmh);
  const items: string[] =
    felt < 0
      ? ["dicke Winterjacke", "Mütze", "Schal", "Handschuhe", "warme Schuhe"]
      : felt < 5
        ? ["Winterjacke", "Mütze", "Schal"]
        : felt < 10
          ? ["warme Jacke", "Schal"]
          : felt < 15
            ? ["Übergangsjacke oder Pullover"]
            : felt < 20
              ? ["Pullover oder leichte Jacke"]
              : ["T-Shirt"];
  const rain = (w.regen_pct ?? 0) >= 40 || (w.code != null && RAIN_CODES.includes(w.code));
  const snow = w.code != null && SNOW_CODES.includes(w.code);
  if (rain || snow) items.push("Regenjacke oder Poncho");
  else if ((w.wind_kmh ?? 0) >= 30 && felt < 20) items.push("etwas Winddichtes");
  if (w.temp_c >= 25 && w.code != null && w.code <= 1) items.push("Kappe und Sonnencreme");
  return items.join(", ");
}
