"use client";

import { useState } from "react";

/** „Anreise mit Bus und Bahn“: Google Maps mit ÖPNV und Ankunft eine Stunde vor dem Anpfiff, Start am aktuellen
 * Standort. Beim Klick wird zuerst im selben Tab der Standort abgefragt (ein vorher geöffnetes Fenster würde die
 * Nachfrage des Browsers verdecken), dann Google Maps mit den Koordinaten als Start geöffnet. Ohne Standort
 * (abgelehnt, keine Antwort nach 10 s, Seite nicht über https oder localhost) gibt es den offiziellen Link ohne
 * Uhrzeit: dort setzt die Google-Maps-App den aktuellen Standort selbst ein. */
export function RouteLink({ template, fallback, arrival }: { template: string; fallback: string; arrival: string }) {
  const [busy, setBusy] = useState(false);
  const time = arrival.slice(11, 16); // Ortszeit am Stadion steht im Zeitstempel ("2026-10-23T19:30+02:00")
  // Koordinaten "lat,lon" mit echtem Komma, sonst erkennt Google sie nicht sicher als Ort
  const withStart = (start: string) => template.replace("{start}", encodeURIComponent(start).replace(/%2C/g, ","));
  const go = (url: string) => {
    setBusy(false);
    const win = window.open(url, "_blank");
    if (win) win.opener = null;
    else window.location.href = url; // Fenster blockiert (Nachfrage dauerte zu lange): im selben Tab
  };
  return (
    <a
      href={fallback}
      target="_blank"
      rel="noopener noreferrer"
      className="relative underline hover:text-foreground"
      title={`Google Maps: Verbindungen mit Bus und Bahn ab deinem Standort, Ankunft bis ${time} Uhr Ortszeit`}
      onClick={(e) => {
        if (!navigator.geolocation || !window.isSecureContext) return; // offizieller Link, App nimmt den Standort
        e.preventDefault();
        setBusy(true);
        let done = false;
        const finish = (url: string) => {
          if (done) return;
          done = true;
          go(url);
        };
        const timer = setTimeout(() => finish(fallback), 10000); // Nachfrage nicht beantwortet
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            clearTimeout(timer);
            finish(withStart(`${pos.coords.latitude.toFixed(5)},${pos.coords.longitude.toFixed(5)}`));
          },
          () => {
            clearTimeout(timer);
            finish(fallback);
          },
          { timeout: 8000, maximumAge: 300000 },
        );
      }}
    >
      {busy ? "Standort wird ermittelt …" : `Anreise mit Bus und Bahn (an ${time} Uhr)`}
    </a>
  );
}
