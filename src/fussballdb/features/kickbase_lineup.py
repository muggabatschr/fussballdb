"""Kickbase-Aufstellung: die Elf mit den meisten erwarteten Punkten am nächsten Spieltag aus dem eigenen
Kader, über alle in Kickbase erlaubten Formationen. Ausfälle (verletzt, gesperrt, laut Kickbase nicht fit)
spielen nicht; sie werden extra aufgeführt."""

import pandas as pd

from fussballdb.features.kickbase_projection import projections

# Kickbase-Formationen (Abwehr, Mittelfeld, Sturm), immer mit einem Torwart
FORMATIONS = [(3, 4, 3), (3, 5, 2), (3, 6, 1), (4, 2, 4), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 2, 3), (5, 3, 2), (5, 4, 1)]
ORDER = ["TW", "ABW", "MF", "ST"]


def best_lineup(squad: pd.DataFrame) -> dict:
    """squad: Zeilen der Projektion (position, kb_punkte, ausfall, …) für den eigenen Kader."""
    fit = squad[squad["ausfall"].isna() & squad["kb_punkte"].notna()]
    by_pos = {p: fit[fit["position"] == p].sort_values("kb_punkte", ascending=False) for p in ORDER}
    best = None
    for d, m, s in FORMATIONS:
        need = {"TW": 1, "ABW": d, "MF": m, "ST": s}
        if any(len(by_pos[p]) < n for p, n in need.items()):
            continue
        chosen = pd.concat([by_pos[p].head(n) for p, n in need.items()])
        total = float(chosen["kb_punkte"].sum())
        if best is None or total > best[0]:
            best = (total, f"{d}-{m}-{s}", chosen)
    cols = ["name", "position", "team_name", "kb_punkte", "einsatz", "gegner"]
    missing = squad[squad["ausfall"].notna()]
    out = {"formation": None, "elf": [], "bank": [], "punkte": None,
           "ausfaelle": [{"name": r.name, "position": r.position, "grund": r.ausfall} for r in missing.itertuples()]}
    if best is None:
        out["hinweis"] = "Zu wenige fitte Spieler für eine gültige Formation (1 Torwart, 3–5 Abwehr, 2–6 Mittelfeld, 1–4 Sturm)."
        return out
    total, formation, chosen = best
    chosen = chosen.assign(_o=chosen["position"].map(ORDER.index)).sort_values(["_o", "kb_punkte"], ascending=[True, False])
    bench = fit[~fit["player_id"].isin(chosen["player_id"])].sort_values("kb_punkte", ascending=False)
    out.update(formation=formation, punkte=round(total), elf=chosen[cols].to_dict("records"),
               bank=bench[cols].to_dict("records"))
    return out


def lineup() -> dict:
    df = projections(1)
    if df.empty:
        return {"formation": None, "elf": [], "bank": [], "ausfaelle": [], "hinweis": "Keine offenen Spiele."}
    squad = df[df["im_kader"]]
    if squad.empty:
        return {"formation": None, "elf": [], "bank": [], "ausfaelle": [],
                "hinweis": "Kein eigener Kader geladen (uv run fussballdb kickbase-login, dann fussballdb kickbase)."}
    return best_lineup(squad)
