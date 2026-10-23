"use client";

import { useState } from "react";
import type { FormGame, TeamColor } from "@/lib/api";
import { Card } from "./Card";
import { FormTable } from "./FormTable";
import { TeamColors } from "./TeamColors";
import { XgChart } from "./XgChart";

/** Diagramm und Spieletabelle der Teamseite mit gemeinsamer Hervorhebung: Maus auf einem Balkenpaar markiert
 * die Zeile, Maus auf einer Zeile das Balkenpaar. `children` steht unter der Tabelle (Legende). */
/** xG in der Vereinsfarbe, xGA neutral grau. */
const NEUTRAL = { hell: "#a8a29e", dunkel: "#78716c" };

export function TeamGames({
  games,
  color,
  children,
}: {
  games: FormGame[];
  color?: TeamColor | null;
  children?: React.ReactNode;
}) {
  const [active, setActive] = useState<number | null>(null);
  return (
    <>
      <Card>
        <h2 className="mb-2 text-sm font-medium">xG und xGA je Spiel</h2>
        <TeamColors colors={color ? { home: color, away: NEUTRAL } : null}>
          <XgChart games={games} active={active} onActive={setActive} />
        </TeamColors>
      </Card>
      <section>
        <h2 className="mb-2 text-sm font-medium">Spiele</h2>
        <FormTable games={games} active={active} onActive={setActive} />
        {children}
      </section>
    </>
  );
}
