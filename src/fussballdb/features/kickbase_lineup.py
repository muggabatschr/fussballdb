"""Kickbase-Aufstellung: die Elf mit den meisten erwarteten Punkten am nächsten Spieltag aus dem eigenen
Kader, über alle in Kickbase erlaubten Formationen. Ausfälle (verletzt, gesperrt, laut Kickbase nicht fit)
spielen nicht; sie werden extra aufgeführt.

Dazu die aktuell in Kickbase gesetzte Elf (kb_league_entry.lineup_pos) mit ihren erwarteten Punkten, das Budget
und Tauschvorschläge: je Kaderspieler der Kauf vom Transfermarkt, der die beste Elf am meisten verbessert,
auch wenn dafür die Formation wechselt (z. B. Mittelfeldspieler raus, Stürmer rein, 4-4-2 → 4-3-3). Gerechnet mit
dem Verkauf an Kickbase zum Marktwert und dem Angebotspreis auf dem Markt (Gebote können höher liegen)."""

import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

from fussballdb.features.kickbase_projection import projections

# Kickbase-Formationen (Abwehr, Mittelfeld, Sturm), immer mit einem Torwart
FORMATIONS = [(3, 4, 3), (3, 5, 2), (3, 6, 1), (4, 2, 4), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 2, 3), (5, 3, 2), (5, 4, 1)]
ORDER = ["TW", "ABW", "MF", "ST"]


def best_lineup(squad: pd.DataFrame) -> dict:
    """squad: Zeilen der Projektion (position, kb_punkte, ausfall, …) für den eigenen Kader. Reichen die fitten
    Spieler für keine Formation, bleiben Plätze leer (0 Punkte); `fehlt` nennt sie je Position."""
    fit = squad[squad["ausfall"].isna() & squad["kb_punkte"].notna()]
    by_pos = {p: fit[fit["position"] == p].sort_values("kb_punkte", ascending=False) for p in ORDER}
    best = None
    for d, m, s in FORMATIONS:
        need = {"TW": 1, "ABW": d, "MF": m, "ST": s}
        chosen = pd.concat([by_pos[p].head(n) for p, n in need.items()])
        missing = {p: n - len(by_pos[p].head(n)) for p, n in need.items() if len(by_pos[p]) < n}
        total = float(chosen["kb_punkte"].sum())
        key = (total, -sum(missing.values()))
        if best is None or key > best[0]:
            best = (key, f"{d}-{m}-{s}", chosen, missing)
    cols = ["name", "position", "team_name", "kb_punkte", "einsatz", "gegner"]
    missing_players = squad[squad["ausfall"].notna()]
    out = {"formation": None, "elf": [], "bank": [], "punkte": None, "fehlt": {},
           "ausfaelle": [{"name": r.name, "position": r.position, "grund": r.ausfall} for r in missing_players.itertuples()]}
    (total, _), formation, chosen, missing = best
    if chosen.empty:
        out["hinweis"] = "Keine fitten Spieler im Kader."
        return out
    chosen = chosen.assign(_o=chosen["position"].map(ORDER.index)).sort_values(["_o", "kb_punkte"], ascending=[True, False])
    bench = fit[~fit["player_id"].isin(chosen["player_id"])].sort_values("kb_punkte", ascending=False)
    out.update(formation=formation, punkte=round(total), elf=chosen[cols].to_dict("records"),
               bank=bench[cols].to_dict("records"), fehlt=missing)
    if missing:
        names = {"TW": "Torwart", "ABW": "Abwehr", "MF": "Mittelfeld", "ST": "Sturm"}
        out["hinweis"] = ("Zu wenige fitte Spieler für eine volle Elf, leer bleibt: "
                          + ", ".join(f"{n}× {names[p]}" for p, n in missing.items()) + ".")
    return out


def _formation(players: pd.DataFrame) -> str | None:
    n = players["position"].value_counts()
    return f"{n.get('ABW', 0)}-{n.get('MF', 0)}-{n.get('ST', 0)}" if len(players) else None


def current_lineup(squad: pd.DataFrame) -> dict | None:
    """Die in Kickbase gesetzte Elf: Formation, erwartete Punkte (Ausfälle zählen 0) und wer davon ausfällt."""
    if "lineup_pos" not in squad or squad["lineup_pos"].isna().all():
        return None
    elf = squad[squad["lineup_pos"].notna()].sort_values("lineup_pos")
    pts = elf["kb_punkte"].where(elf["ausfall"].isna()).fillna(0)
    return {"formation": _formation(elf), "punkte": round(float(pts.sum())),
            "elf": [{"name": r.name, "position": r.position, "team_name": r.team_name,
                     "kb_punkte": None if pd.isna(r.kb_punkte) else r.kb_punkte,
                     "ausfall": None if pd.isna(r.ausfall) else r.ausfall} for r in elf.itertuples()]}


def budget() -> dict:
    with engine.connect() as conn:
        r = conn.execute(text("SELECT budget, max_players FROM kb_league_info LIMIT 1")).first()
    return {"budget": r.budget, "max_spieler": r.max_players} if r else {"budget": None, "max_spieler": None}


def swaps(squad: pd.DataFrame, market: pd.DataFrame, money: float | None, top: int = 3) -> list[dict]:
    """Je Kaderspieler der beste Tausch gegen einen Spieler vom Transfermarkt, gemessen an den erwarteten Punkten
    der besten Elf danach. Nur Tausche, die die Elf verbessern und bezahlbar sind (Budget danach nicht negativ;
    ein negatives Budget beim Anpfiff kostet in Kickbase alle Punkte des Spieltags)."""
    base = best_lineup(squad)
    base_pts = sum(p["kb_punkte"] for p in base["elf"]) if base["elf"] else 0.0
    buys = market[market["ausfall"].isna() & (market["einsatz"] >= 0.5) & market["kb_punkte"].notna()]
    out = []
    for s in squad.itertuples():
        rest = squad[squad["player_id"] != s.player_id]
        best = None
        for b in buys.itertuples():
            after = best_lineup(pd.concat([rest, buys[buys["player_id"] == b.player_id]]))
            if not after["elf"]:
                continue
            gain = sum(p["kb_punkte"] for p in after["elf"]) - base_pts
            left = None if money is None else money + (s.marktwert or 0) - b.markt_preis
            cand = (left is None or left >= 0, gain, b, after, left)
            if gain > 0.5 and (best is None or cand[:2] > best[:2]):
                best = cand
        if best and best[0]:  # nur bezahlbare Tausche
            ok, gain, b, after, left = best
            out.append({"verkauf_id": int(s.player_id), "verkauf": s.name, "verkauf_position": s.position,
                        "verkauf_wert": s.marktwert, "kauf": b.name, "kauf_position": b.position,
                        "kauf_team": b.team_name, "kauf_preis": b.markt_preis, "kauf_punkte": b.kb_punkte,
                        "mehr_punkte": round(gain, 1), "formation_vorher": base["formation"],
                        "formation_nachher": after["formation"], "budget_danach": left, "bezahlbar": ok})
    out.sort(key=lambda x: x["mehr_punkte"], reverse=True)
    return out


def lineup() -> dict:
    df = projections(1)
    if df.empty:
        return {"formation": None, "elf": [], "bank": [], "ausfaelle": [], "hinweis": "Keine offenen Spiele."}
    squad = df[df["im_kader"]]
    if squad.empty:
        return {"formation": None, "elf": [], "bank": [], "ausfaelle": [],
                "hinweis": "Kein eigener Kader geladen (uv run fussballdb kickbase-login, dann fussballdb kickbase)."}
    out = best_lineup(squad)
    money = budget()
    market = df[df["markt_preis"].notna() & ~df["im_kader"]]
    out.update(aktuell=current_lineup(squad), **money, tausch=swaps(squad, market, money["budget"]))
    return out
