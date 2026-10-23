import type { PitchPlayer, PitchTeam } from "@/lib/api";
import { num } from "@/lib/format";
import { TeamName } from "./TeamName";

/** Farbe der Note wie bei FotMob: ab 8 blau, ab 7 grün, ab 6 orange, darunter rot. */
const ratingClass = (r: number) =>
  r >= 8 ? "bg-sky-500" : r >= 7 ? "bg-green-600" : r >= 6 ? "bg-amber-500" : "bg-red-600";

function Rating({ p }: { p: PitchPlayer }) {
  if (p.note == null) return null;
  return (
    <span
      className={`rounded-full px-1.5 text-[10px] leading-4 font-semibold whitespace-nowrap text-white tabular-nums ${
        p.spieler_des_spiels ? "bg-sky-500" : ratingClass(p.note)
      }`}
      title={p.spieler_des_spiels ? "Spieler des Spiels" : "Note laut FotMob"}
    >
      {num(p.note, 1)}
      {p.spieler_des_spiels && " ★"}
    </span>
  );
}

/** Tore, Vorlagen, Karten als kleine Zeichen hinter dem Namen. */
function Marks({ p }: { p: PitchPlayer }) {
  const marks: [string, string][] = [];
  for (let i = 0; i < p.tore; i++) marks.push(["⚽", "Tor"]);
  for (let i = 0; i < p.eigentore; i++) marks.push(["⚽", "Eigentor"]);
  for (let i = 0; i < p.vorlagen; i++) marks.push(["🅰", "Vorlage"]);
  for (let i = 0; i < p.elfmeter_verschossen; i++) marks.push(["✕", "Elfmeter verschossen"]);
  for (let i = 0; i < p.elfmeter_gehalten; i++) marks.push(["🧤", "Elfmeter gehalten"]);
  return (
    <>
      {p.gelb && !p.rot && <span className="inline-block h-3 w-2 rounded-[1px] bg-yellow-400" title="Gelbe Karte" />}
      {p.rot && <span className="inline-block h-3 w-2 rounded-[1px] bg-red-600" title="Rote Karte" />}
      {marks.map(([m, t], i) => (
        <span key={i} title={t} className={t === "Eigentor" ? "opacity-60 grayscale" : ""}>
          {m}
        </span>
      ))}
    </>
  );
}

/** Ein Spieler auf dem Feld: Kreis mit Rückennummer in Teamfarbe, Note, Auswechslung, Name mit Zeichen. */
function Player({ p, side, left, top }: { p: PitchPlayer; side: "home" | "away"; left: number; top: number }) {
  return (
    <div
      className="absolute flex w-20 -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center sm:w-24"
      style={{ left: `${left}%`, top: `${top}%` }}
      title={p.voller_name}
    >
      <div className="relative">
        {p.raus != null && (
          <span className="absolute -top-4 -left-3 text-[10px] text-red-500 tabular-nums" title={`ausgewechselt (${p.raus}.)`}>
            ↓{p.raus}′
          </span>
        )}
        <span
          className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold sm:h-9 sm:w-9 ${
            side === "home" ? "bg-home" : "bg-away"
          }`}
          style={{ color: `var(--${side}-fg)` }}
        >
          {p.nummer ?? ""}
        </span>
        <span className="absolute -top-2 left-5 sm:left-6">
          <Rating p={p} />
        </span>
      </div>
      <span className="mt-0.5 flex max-w-full items-center justify-center gap-0.5 text-[11px] leading-tight sm:text-xs">
        {p.kapitaen && (
          <span className="rounded-full border border-current px-[3px] text-[8px] leading-3 text-muted" title="Kapitän">
            C
          </span>
        )}
        <span className="truncate">{p.name}</span>
      </span>
      <span className="flex h-3.5 items-center gap-0.5 text-[10px] leading-none">
        <Marks p={p} />
      </span>
    </div>
  );
}

/** Spielfeldlinien (Mittellinie, Mittelkreis, Strafräume); waagerecht oder senkrecht. */
function Lines({ vertical }: { vertical: boolean }) {
  const line = "absolute border-border";
  return vertical ? (
    <>
      <div className={`${line} inset-x-0 top-1/2 border-t`} />
      <div className={`${line} top-1/2 left-1/2 h-[18%] w-[30%] -translate-x-1/2 -translate-y-1/2 rounded-full border`} />
      <div className={`${line} top-0 left-1/2 h-[14%] w-[56%] -translate-x-1/2 border border-t-0`} />
      <div className={`${line} bottom-0 left-1/2 h-[14%] w-[56%] -translate-x-1/2 border border-b-0`} />
    </>
  ) : (
    <>
      <div className={`${line} inset-y-0 left-1/2 border-l`} />
      <div className={`${line} top-1/2 left-1/2 h-[30%] w-[18%] -translate-x-1/2 -translate-y-1/2 rounded-full border`} />
      <div className={`${line} top-1/2 left-0 h-[56%] w-[14%] -translate-y-1/2 border border-l-0`} />
      <div className={`${line} top-1/2 right-0 h-[56%] w-[14%] -translate-y-1/2 border border-r-0`} />
    </>
  );
}

/** Kopfzeile je Team: Wappen, Name, Formation, Teamnote. */
function TeamHead({ t, label, align }: { t: PitchTeam; label: string; align: "start" | "end" }) {
  return (
    <div className={`flex min-w-0 items-center gap-2 ${align === "end" ? "flex-row-reverse text-right max-sm:self-end" : ""}`}>
      <TeamName name={label} short logoSize={20} link={false} align={align} />
      {t.formation && <span className="font-semibold whitespace-nowrap tabular-nums">{t.formation}</span>}
      {t.note != null && (
        <span className={`rounded-full px-1.5 text-xs leading-5 font-semibold text-white ${ratingClass(t.note)}`} title="Teamnote laut FotMob">
          {num(t.note, 1)}
        </span>
      )}
    </div>
  );
}

/** Bank: Eingewechselte mit Minute und Note, dann die übrigen Ersatzspieler, darunter der Trainer. */
function Bench({ t, label }: { t: PitchTeam; label: string }) {
  const used = t.bank.filter((p) => p.rein != null).sort((a, b) => (a.rein ?? 0) - (b.rein ?? 0));
  const rest = t.bank.filter((p) => p.rein == null);
  return (
    <div className="min-w-0 space-y-1 text-xs">
      <TeamName name={label} short logoSize={14} link={false} className="font-medium" />
      {used.map((p) => (
        <div key={p.voller_name} className="flex items-center gap-1.5">
          <span className="w-8 text-green-600 tabular-nums">↑{p.rein}′</span>
          <span className="w-5 text-right text-muted tabular-nums">{p.nummer}</span>
          <span className="truncate">{p.voller_name}</span>
          <span className="flex items-center gap-0.5 text-[10px]">
            <Marks p={p} />
          </span>
          <span className="ml-auto">
            <Rating p={p} />
          </span>
        </div>
      ))}
      {rest.length > 0 && (
        <p className="text-muted">
          Bank: {rest.map((p) => p.name).join(", ")}
        </p>
      )}
      {t.trainer && <p className="text-muted">Trainer: {t.trainer}</p>}
    </div>
  );
}

/** Aufstellung auf dem Spielfeld wie bei FotMob: am Desktop waagerecht (Heim links, Gast rechts), auf dem Handy
 * senkrecht (Heim oben). Der Gast ist gespiegelt, beide spielen aufeinander zu. */
export function Pitch({ home, away, homeName, awayName }: { home: PitchTeam; away: PitchTeam; homeName: string; awayName: string }) {
  const placed = (t: PitchTeam) => t.startelf.filter((p) => p.x != null && p.y != null);
  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex flex-col gap-1 border-b border-border px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <TeamHead t={home} label={homeName} align="start" />
        <TeamHead t={away} label={awayName} align="end" />
      </div>
      {/* waagerecht ab sm */}
      <div className="relative mx-3 my-3 aspect-[16/10] overflow-hidden rounded-md border border-border max-sm:hidden">
        <Lines vertical={false} />
        {placed(home).map((p) => (
          <Player key={p.voller_name} p={p} side="home" left={p.x! * 50} top={p.y! * 100} />
        ))}
        {placed(away).map((p) => (
          <Player key={p.voller_name} p={p} side="away" left={100 - p.x! * 50} top={100 - p.y! * 100} />
        ))}
      </div>
      {/* senkrecht auf dem Handy */}
      <div className="relative mx-auto my-3 aspect-[10/19] w-[calc(100%-1.5rem)] overflow-hidden rounded-md border border-border sm:hidden">
        <Lines vertical />
        {/* Rand oben und unten, damit der Torwart samt Note nicht angeschnitten wird; seitlich etwas Luft */}
        {placed(home).map((p) => (
          <Player key={p.voller_name} p={p} side="home" left={8 + (p.vx ?? 1 - p.y!) * 84} top={2 + (p.vy ?? p.x!) * 48} />
        ))}
        {placed(away).map((p) => (
          <Player key={p.voller_name} p={p} side="away" left={92 - (p.vx ?? 1 - p.y!) * 84} top={98 - (p.vy ?? p.x!) * 48} />
        ))}
      </div>
      <div className="grid gap-4 border-t border-border px-3 py-3 sm:grid-cols-2">
        <Bench t={home} label={homeName} />
        <Bench t={away} label={awayName} />
      </div>
    </div>
  );
}
