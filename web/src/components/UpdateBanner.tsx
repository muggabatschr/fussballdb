"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

type Status = { update: { running: boolean; step: string | null } };

/** Zeigt an, wenn die API gerade Daten aktualisiert, und lädt die Seite danach neu. */
export function UpdateBanner() {
  const router = useRouter();
  const [step, setStep] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const wasRunning = useRef(false);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as Status;
        if (!active) return;
        setRunning(data.update.running);
        setStep(data.update.step);
        if (wasRunning.current && !data.update.running) router.refresh();
        wasRunning.current = data.update.running;
      } catch {
        // API nicht erreichbar: kein Hinweis, die Seiten zeigen dann selbst einen Fehler
      }
    };
    poll();
    const id = setInterval(poll, 10_000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [router]);

  if (!running) return null;
  return (
    <div className="border-b border-border bg-accent/10 text-sm" role="status">
      <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-2">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
        Daten werden aktualisiert{step ? `: ${step}` : ""}. Die Seite lädt danach automatisch neu.
      </div>
    </div>
  );
}
