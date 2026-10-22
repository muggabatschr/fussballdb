import type { Venue } from "@/lib/api";
import { num } from "@/lib/format";
import { clothingAdvice, weatherText } from "@/lib/weather";
import { RouteLink } from "./RouteLink";

/** Stadion mit Kapazität, darunter das Wetter zur Spielzeit (Vorhersage oder gemessen) und vor dem Spiel eine
 * Kleidungsempfehlung für Zuschauer. */
export function VenueLine({ ort, className = "" }: { ort?: Venue | null; className?: string }) {
  if (!ort) return null;
  const w = ort.wetter;
  const parts = w
    ? [
        w.temp_c != null ? `${num(w.temp_c, 0)} °C` : null,
        weatherText(w.code),
        w.art === "vorhersage" && w.regen_pct != null ? `Regen ${Math.round(w.regen_pct)} %` : null,
        w.art === "gemessen" && w.regen_mm ? `${num(w.regen_mm, 1)} mm Regen` : null,
        w.wind_kmh != null ? `Wind ${Math.round(w.wind_kmh)} km/h` : null,
      ].filter(Boolean)
    : [];
  const clothing = w?.art === "vorhersage" ? clothingAdvice(w) : null;
  return (
    <div className={`space-y-0.5 text-xs text-muted ${className}`}>
      <p className="truncate" title={[ort.stadion, ort.stadt].filter(Boolean).join(", ")}>
        <span className="text-foreground/80">{ort.stadion}</span>
        {ort.kapazitaet ? <span className="tabular"> · {ort.kapazitaet.toLocaleString("de-DE")} Plätze</span> : null}
      </p>
      {parts.length > 0 && (
        <p className="truncate tabular" title={w?.art === "vorhersage" ? "Vorhersage zur Spielzeit (Open-Meteo)" : "Wetter zur Spielzeit (Open-Meteo)"}>
          {parts.join(" · ")}
          {w?.art === "vorhersage" && <span className="opacity-70"> (Vorhersage)</span>}
        </p>
      )}
      {clothing && (
        <p className="truncate" title="Empfehlung für Zuschauer nach gefühlter Temperatur (Wind, 90 Minuten im Stadion), Regen und Sonne">
          <span className="text-foreground/80">Anziehen:</span> {clothing}
        </p>
      )}
      {ort.anreise && (
        <p className="truncate">
          <RouteLink template={ort.anreise.url_vorlage} fallback={ort.anreise.url_ohne_zeit} arrival={ort.anreise.ankunft} />
        </p>
      )}
    </div>
  );
}
