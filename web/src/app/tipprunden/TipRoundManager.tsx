"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { TipRound } from "@/lib/api";

async function call(body: object): Promise<string | null> {
  const res = await fetch("/api/tipprunden", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (res.ok) return null;
  return (await res.json().catch(() => ({}))).detail ?? "Das hat nicht geklappt.";
}

/** Tipprunde per Kicktipp-Link hinzufügen; Knöpfe zum Standard-Setzen und Löschen je Runde. */
export function AddTipRound() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        const err = await call({ action: "add", url, name });
        setBusy(false);
        setError(err);
        if (!err) {
          setUrl("");
          setName("");
          router.refresh();
        }
      }}
    >
      <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-muted">
        Kicktipp-Link
        <input
          id="tipprunde-url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.kicktipp.de/meine-runde/"
          className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-foreground"
        />
      </label>
      <label className="flex w-40 flex-col gap-1 text-xs text-muted">
        Anzeigename (optional)
        <input
          id="tipprunde-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-foreground"
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm hover:border-accent disabled:opacity-50"
      >
        {busy ? "Lese Regeln …" : "Hinzufügen"}
      </button>
      {error && <p className="w-full text-sm text-away">{error}</p>}
    </form>
  );
}

export function RoundActions({ round }: { round: TipRound }) {
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);
  const btn = "rounded-lg border border-border px-2 py-1 text-xs hover:border-accent";
  const run = async (action: string) => {
    await call({ action, slug: round.slug });
    setConfirm(false);
    router.refresh();
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {!round.standard && (
        <button type="button" className={btn} onClick={() => run("standard")}>
          Als Standard
        </button>
      )}
      {confirm ? (
        <>
          <span className="text-xs text-muted">Wirklich löschen?</span>
          <button type="button" className={`${btn} text-away`} onClick={() => run("delete")}>
            Ja, löschen
          </button>
          <button type="button" className={btn} onClick={() => setConfirm(false)}>
            Abbrechen
          </button>
        </>
      ) : (
        <button type="button" className={btn} onClick={() => setConfirm(true)}>
          Löschen
        </button>
      )}
    </div>
  );
}
