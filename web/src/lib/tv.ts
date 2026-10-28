/** Senderlogos unter /public/tv: Kanalname (wie von der API) -> Bild, Originalgröße, Zusatztext.
 * Die Bilder werden unverändert ausgeliefert (unoptimized), damit sie auf Retina-Displays scharf bleiben. */
export type TvLogo = { src: string; w: number; h: number; pill: boolean; suffix?: string };

const logo = (file: string, w: number, h: number, pill = true): TvLogo => ({ src: `/tv/${file}`, w, h, pill });

export function tvLogo(channel: string): TvLogo | null {
  let m = channel.match(/^Sky (?:Sport )?Bundesliga (\d+)$/);
  if (m) return logo(`sky-bundesliga-${m[1]}.png`, m[1] === "10" ? 296 : 284, 46);
  if (/^Sky (Sport )?Bundesliga$/.test(channel)) return logo("sky-bundesliga.png", 248, 46);
  if (/^Sky (Sport )?Top Event$/.test(channel)) return logo("sky-top-event.png", 368, 46);
  // Sky Sport 1–10 (Pokal, 2. Liga): Sky-Bundesliga-Logo ohne Bundesliga-Wappen; "(Konferenz)" als Zusatz
  m = channel.match(/^Sky Sport (\d+)( \(Konferenz\))?$/);
  if (m) return { ...logo(`sky-sport-${m[1]}.png`, m[1] === "10" ? 261 : 249, 46), suffix: m[2] ? "Konferenz" : undefined };
  m = channel.match(/^Sky Sport Austria(?: (\d+))?$/);
  if (m) return { ...logo("sky-sport-austria.png", 320, 46), suffix: m[1] };
  if (channel === "DAZN") return logo("dazn.png", 400, 400, false);
  if (channel === "WOW") return logo("wow.svg", 127, 47, false);
  if (channel === "Prime Video") return logo("prime-video.png", 960, 302);
  // Wikimedia Commons; Livestreams und Mediatheken mit dem Logo ihres Senders (werden zusammengefasst)
  if (channel === "RTL+") return logo("rtl-plus.png", 500, 74);
  if (channel === "RTL") return logo("rtl.png", 500, 88);
  if (/^OneFootball/.test(channel)) return logo("onefootball.png", 500, 70);
  if (/^ZDF/.test(channel)) return logo("zdf.png", 250, 150);
  if (/^(Das Erste|ARD-Mediathek|Sportschau\.de)$/.test(channel)) return logo("das-erste.png", 120, 105);
  if (/^Servus ?TV/.test(channel)) return logo("servustv.png", 250, 111);
  if (/^Sportdigital (FUSSBALL|Fußball)$/i.test(channel)) return logo("sportdigital-fussball.png", 500, 126);
  return null;
}
