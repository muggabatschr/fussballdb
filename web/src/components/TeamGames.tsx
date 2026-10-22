"use client";

import { useState } from "react";
import type { FormGame } from "@/lib/api";
import { Card } from "./Card";
import { FormTable } from "./FormTable";
import { XgChart } from "./XgChart";

/** Diagramm und Spieletabelle der Teamseite mit gemeinsamer Hervorhebung: Maus auf einem Balkenpaar markiert
 * die Zeile, Maus auf einer Zeile das Balkenpaar. `children` steht unter der Tabelle (Legende). */
export function TeamGames({ games, children }: { games: FormGame[]; children?: React.ReactNode }) {
  const [active, setActive] = useState<number | null>(null);
  return (
    <>
      <Card>
        <h2 className="mb-2 text-sm font-medium">xG und xGA je Spiel</h2>
        <XgChart games={games} active={active} onActive={setActive} />
      </Card>
      <section>
        <h2 className="mb-2 text-sm font-medium">Spiele</h2>
        <FormTable games={games} active={active} onActive={setActive} />
        {children}
      </section>
    </>
  );
}
