"""Torschützen-Prognose: Chance je Spieler, im nächsten Spiel mindestens ein Tor zu schießen.

Grundlage sind die erwarteten Tore je Spieler aus der Spielerprojektion (features/kickbase_projection.py):
xG pro 90 Minuten (geglättet zum Positionsschnitt), erwartete Minuten aus Startelf-Quote, voraussichtlicher
Aufstellung und Ausfällen, skaliert mit der Torerwartung des Teams gegen diesen Gegner aus der Live-Prognose.
Mit Poisson: P(mindestens ein Tor) = 1 − e^(−erwartete Tore).
"""

from math import exp

import pandas as pd

from fussballdb.features.kickbase_projection import match_rows


def scorers(matchdays: int = 1, top: int = 3) -> dict[int, dict[int, list[dict]]]:
    """Match-ID -> Team-ID -> die `top` wahrscheinlichsten Torschützen [{name, p, tore}]."""
    df = match_rows(matchdays)
    if df.empty:
        return {}
    df = df[df["ausfall"].isna() & (df["tore"] > 0)].copy()
    df["p"] = df["tore"].map(lambda x: 1 - exp(-x))
    out: dict[int, dict[int, list[dict]]] = {}
    for (match_id, team_id), g in df.sort_values("p", ascending=False).groupby(["match_id", "team_id"], sort=False):
        out.setdefault(int(match_id), {})[int(team_id)] = [
            {"name": r.name, "p": round(float(r.p), 3), "tore": round(float(r.tore), 2)} for r in g.head(top).itertuples()]
    return out


def as_frame(matchdays: int = 1) -> pd.DataFrame:
    """Alle Spieler mit Torchance, absteigend (für Chat und MCP)."""
    df = match_rows(matchdays)
    if df.empty:
        return df
    df = df[df["ausfall"].isna() & (df["tore"] > 0)].copy()
    df["p_tor"] = (1 - (-df["tore"]).map(exp)).round(3)
    return df.sort_values("p_tor", ascending=False)[["name", "team_name", "gegner", "position", "einsatz", "tore", "p_tor"]]
