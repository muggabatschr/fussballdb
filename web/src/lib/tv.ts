/** Senderlogos unter /public/tv: Kanalname (wie von der API) -> Bild, Originalgröße, Zusatztext.
 * Die Bilder werden unverändert ausgeliefert (unoptimized), damit sie auf Retina-Displays scharf bleiben. */
export type TvLogo = { src: string; w: number; h: number; pill: boolean; suffix?: string };

const logo = (file: string, w: number, h: number, pill = true): TvLogo => ({ src: `/tv/${file}`, w, h, pill });

export function tvLogo(channel: string): TvLogo | null {
  let m = channel.match(/^Sky (?:Sport )?Bundesliga (\d+)$/);
  if (m) return logo(`sky-bundesliga-${m[1]}.png`, m[1] === "10" ? 296 : 284, 46);
  if (/^Sky (Sport )?Bundesliga$/.test(channel)) return logo("sky-bundesliga.png", 248, 46);
  if (/^Sky (Sport )?Top Event$/.test(channel)) return logo("sky-top-event.png", 368, 46);
  m = channel.match(/^Sky Sport Austria(?: (\d+))?$/);
  if (m) return { ...logo("sky-sport-austria.png", 320, 46), suffix: m[1] };
  if (channel === "DAZN") return logo("dazn.png", 400, 400, false);
  if (channel === "WOW") return logo("wow.svg", 127, 47, false);
  if (channel === "Prime Video") return logo("prime-video.png", 960, 302);
  return null;
}
