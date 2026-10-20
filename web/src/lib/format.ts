export const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)} %`);

export const num = (v: number | null | undefined, digits = 2) =>
  v == null ? "–" : v.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const kickoff = (iso: string) =>
  new Date(iso).toLocaleString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Berlin",
  });

export const teamHref = (name: string) => `/team/${encodeURIComponent(name)}`;
