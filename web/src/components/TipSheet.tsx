"use client";

import Link from "next/link";
import { useState } from "react";
/** Ein Spiel auf dem Tipp-Zettel (Bundesliga-Spieltag oder Runde von 2. Liga, CL, Pokal). */
export type TipGame = { id: number; kickoff: string; home: string; away: string; tip_home: number | null; tip_away: number | null };
export type TipSheetProps = {
  title: string; // "7. Spieltag", "2. Runde"
  subtitle: string; // "Bundesliga 2026/27"
  games: TipGame[];
  backHref: string;
  backLabel: string;
  fileName: string;
};
import { resolveTeam, shortName } from "@/lib/teams";
import { TeamName } from "./TeamName";

const day = (iso: string) =>
  new Date(iso).toLocaleString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Berlin",
  });

const loadImage = (src: string) =>
  new Promise<HTMLImageElement | null>((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });

/** Tipp-Zettel als PNG zeichnen (mit Wappen), z. B. zum Weiterleiten per Messenger. */
async function renderImage({ title, subtitle, games }: TipSheetProps): Promise<Blob | null> {
  const scale = 2; // scharf auf Handy-Displays
  const w = 640;
  const rowH = 52;
  const top = 92;
  const h = top + games.length * rowH + 44;
  const canvas = document.createElement("canvas");
  canvas.width = w * scale;
  canvas.height = h * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(scale, scale);
  const font = "system-ui, -apple-system, Segoe UI, sans-serif";
  ctx.fillStyle = "#14161a";
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#f2f2f2";
  ctx.font = `600 24px ${font}`;
  ctx.fillText(`Tipp-Zettel ${title}`, 24, 42);
  ctx.fillStyle = "#9aa0a6";
  ctx.font = `15px ${font}`;
  ctx.fillText(subtitle, 24, 68);

  const logos = await Promise.all(
    games.flatMap((g) => [g.home, g.away]).map((n) => {
      const src = resolveTeam(n)?.info.logo;
      return src ? loadImage(src) : Promise.resolve(null);
    }),
  );
  games.forEach((g, i) => {
    const y = top + i * rowH;
    if (i % 2 === 0) {
      ctx.fillStyle = "#1b1e23";
      ctx.fillRect(12, y, w - 24, rowH);
    }
    const mid = y + rowH / 2;
    ctx.fillStyle = "#9aa0a6";
    ctx.font = `13px ${font}`;
    ctx.fillText(day(g.kickoff), 24, mid + 5);
    // Wappen in ein 26×26-Feld einpassen (breite Wappen sonst über dem Namen)
    const draw = (img: HTMLImageElement | null, x: number) => {
      if (!img || !img.width || !img.height) return;
      const f = Math.min(26 / img.width, 26 / img.height);
      const iw = img.width * f;
      const ih = img.height * f;
      ctx.drawImage(img, x + (26 - iw) / 2, mid - ih / 2, iw, ih);
    };
    draw(logos[2 * i], 150);
    ctx.fillStyle = "#f2f2f2";
    ctx.font = `500 17px ${font}`;
    ctx.fillText(`${shortName(g.home)}  –  ${shortName(g.away)}`, 182, mid + 6);
    const textEnd = 182 + ctx.measureText(`${shortName(g.home)}  –  ${shortName(g.away)}`).width;
    draw(logos[2 * i + 1], textEnd + 10);
    ctx.font = `700 22px ${font}`;
    const tip = `${g.tip_home ?? "–"}:${g.tip_away ?? "–"}`;
    ctx.fillText(tip, w - 24 - ctx.measureText(tip).width, mid + 8);
  });
  ctx.fillStyle = "#6b7178";
  ctx.font = `12px ${font}`;
  ctx.fillText("Tipp = meiste erwartete Punkte nach der Punkteregel der Tipprunde", 24, h - 18);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

/** Alle Tipps eines Spieltags kompakt, zum Abschreiben, Kopieren oder als Bild (z. B. für Kicktipp). */
export function TipSheet(props: TipSheetProps) {
  const { title, subtitle, games, backHref, backLabel, fileName } = props;
  const [copied, setCopied] = useState(false);
  const text = [
    `${title} · ${subtitle}`,
    ...games.map((g) => `${day(g.kickoff)}  ${shortName(g.home)} – ${shortName(g.away)}  ${g.tip_home ?? "–"}:${g.tip_away ?? "–"}`),
  ].join("\n");
  const [imgState, setImgState] = useState<"" | "busy" | "done">("");
  const saveImage = async () => {
    setImgState("busy");
    const blob = await renderImage(props);
    if (!blob) return setImgState("");
    const file = new File([blob], fileName, { type: "image/png" });
    try {
      // Handy: Teilen-Menü (Messenger, Fotos …); sonst herunterladen
      if (navigator.canShare?.({ files: [file] })) {
        // nur die Datei teilen: mit Titel oder Text legt WhatsApp das Bild doppelt an
        await navigator.share({ files: [file] });
      } else {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = file.name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      setImgState("done");
      setTimeout(() => setImgState(""), 2000);
    } catch {
      setImgState(""); // Teilen abgebrochen
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="min-w-0 truncate whitespace-nowrap text-xl font-semibold">
          Tipp-Zettel <span className="text-muted">{title} · {subtitle}</span>
        </h1>
        <div className="flex items-center gap-3 text-sm">
          <button
            type="button"
            onClick={saveImage}
            disabled={imgState === "busy"}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 hover:border-accent disabled:opacity-50"
          >
            {imgState === "busy" ? "Erstelle Bild …" : imgState === "done" ? "Fertig" : "Als Bild"}
          </button>
          <button
            type="button"
            onClick={copy}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 hover:border-accent"
          >
            {copied ? "Kopiert" : "Als Text"}
          </button>
          <Link href={backHref} className="text-muted underline hover:text-foreground">
            {backLabel}
          </Link>
        </div>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-surface">
        <table className="w-full text-sm tabular">
          <tbody>
            {games.map((g) => (
              <tr key={g.id} className="border-b border-border last:border-0">
                <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted">{day(g.kickoff)}</td>
                <td className="w-full max-w-0 px-2 py-2.5">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <TeamName name={g.home} short />
                    <span className="text-muted">–</span>
                    <TeamName name={g.away} short />
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right text-lg font-semibold">
                  {g.tip_home ?? "–"}:{g.tip_away ?? "–"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        Tipp = Ergebnis mit den meisten erwarteten Punkten nach der Punkteregel der Tipprunde, Stand der letzten
        Prognose. Bis zum Anpfiff kann sich ein Tipp noch ändern, wenn neue Ausfälle oder Daten dazukommen.
      </p>
    </div>
  );
}
