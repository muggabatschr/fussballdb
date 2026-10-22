"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Card } from "@/components/Card";
import type { KickbaseStatus } from "@/lib/api";

const date = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "?";

/** Kickbase-Anmeldung im Tab: E-Mail und Passwort gehen nur einmal an Kickbase, gespeichert wird nur das Token. */
export function KickbaseLogin({ initial }: { initial: KickbaseStatus }) {
  const router = useRouter();
  const [status, setStatus] = useState(initial);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function call(action: "login" | "liga" | "logout", body?: object) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/kickbase/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Fehler bei der Anmeldung");
      setStatus(data);
      setPassword("");
      if (action !== "logout") setInfo("Kader, Markt und Marktwerte werden geladen, das dauert etwa eine Minute.");
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler bei der Anmeldung");
    } finally {
      setBusy(false);
    }
  }

  if (status.angemeldet) {
    const leagues = status.ligen ?? [];
    return (
      <Card className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <span className="whitespace-nowrap text-muted">
          Kickbase verbunden · gültig bis {date(status.gueltig_bis)}
        </span>
        {leagues.length > 1 ? (
          <select
            aria-label="Kickbase-Liga"
            value={status.liga ?? ""}
            disabled={busy}
            onChange={(e) => call("liga", { league_id: e.target.value })}
            className="rounded-lg border border-border bg-surface px-2 py-1 text-sm"
          >
            {leagues.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        ) : (
          <span className="whitespace-nowrap">Liga: {leagues[0]?.name ?? "–"}</span>
        )}
        <button
          type="button"
          onClick={() => call("logout")}
          disabled={busy}
          className="ml-auto text-muted underline hover:text-foreground disabled:opacity-50"
        >
          Abmelden
        </button>
        {info && <p className="w-full text-xs text-muted">{info}</p>}
        {error && <p className="w-full text-xs text-away">{error}</p>}
      </Card>
    );
  }

  return (
    <Card className="space-y-3">
      <div>
        <h2 className="text-sm font-medium">Mit Kickbase verbinden</h2>
        <p className="text-xs text-muted">
          {status.abgelaufen
            ? "Die Anmeldung ist abgelaufen (nach etwa einer Woche). Bitte neu anmelden."
            : "Für deinen Kader, den Markt deiner Liga und die Aufstellung. Ein kostenloses Konto reicht."}{" "}
          E-Mail und Passwort gehen nur einmal an Kickbase; gespeichert wird nur der Zugangsschlüssel (Token), nie das
          Passwort.
        </p>
      </div>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (email && password) call("login", { email, password });
        }}
      >
        <input
          type="email"
          autoComplete="username"
          placeholder="E-Mail"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm"
        />
        <input
          type="password"
          autoComplete="current-password"
          placeholder="Passwort"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !email || !password}
          className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:text-black"
        >
          {busy ? "Melde an …" : "Anmelden"}
        </button>
      </form>
      {error && <p className="text-xs text-away">{error}</p>}
    </Card>
  );
}
