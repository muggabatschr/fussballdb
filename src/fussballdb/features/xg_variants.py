"""Varianten von xG pro Team und Spiel, abgeleitet aus den Understat-Schüssen.

- xg:       Spielwert von Understat (wie bisher)
- npxg:     ohne Elfmeter (ob es Elfmeter gibt, ist weitgehend Zufall)
- npxg_pen: npxg plus durchschnittlicher Elfmeterwert der Liga
- close:    npxg, korrigiert auf knappe Spielstände (Abstand höchstens ein Tor). Ein Team, das hoch
            führt, schaltet zurück, ein hoch zurückliegendes drängt; beides verzerrt die Stärke.
- red:      Spiel mit Roter Karte (Zeitpunkt liefert Understat nicht)
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

SHOTS_SQL = text(
    """
    SELECT s.match_id, s.team_id, s.minute, s.xg, s.result, s.situation, m.home_team_id, m.away_team_id
    FROM shot s JOIN match m ON m.id = s.match_id
    ORDER BY s.match_id, s.minute, s.id
    """
)
STATS_SQL = text(
    """
    SELECT x.match_id, x.team_id, x.xg, x.npxg,
           coalesce((SELECT sum(pm.red_cards) FROM player_match pm
                     WHERE pm.match_id = x.match_id AND pm.team_id = x.team_id), 0) AS reds
    FROM match_team_stats x JOIN match m ON m.id = x.match_id JOIN season s ON s.id = m.season_id
    WHERE m.finished AND s.start_year >= 2014  -- ältere Saisons haben kein xG (config.MODEL_FIRST_SEASON)
    """
)
PRIOR_MINUTES = 30.0  # Glättung: so viele Minuten "durchschnittlicher" Spielstand werden dazugerechnet


def _close_factors(shots: pd.DataFrame) -> pd.DataFrame:
    """Pro Team und Spiel: Verhältnis npxG-Rate bei knappem Spielstand zur npxG-Rate insgesamt."""
    out = []
    for match_id, g in shots.groupby("match_id", sort=False):
        home, away = g["home_team_id"].iat[0], g["away_team_id"].iat[0]
        diff = 0  # Heim minus Gast
        events = []  # (minute, Spielstand-Differenz ab dieser Minute)
        close_xg = {home: 0.0, away: 0.0}
        all_xg = {home: 0.0, away: 0.0}
        for r in g.itertuples():
            np_xg = 0.0 if r.situation == "Penalty" else r.xg
            all_xg[r.team_id] += np_xg
            if abs(diff) <= 1:
                close_xg[r.team_id] += np_xg
            if r.result == "Goal":
                diff += 1 if r.team_id == home else -1
                events.append((r.minute, diff))
            elif r.result == "OwnGoal":  # zählt für den Gegner des Schützen
                diff += -1 if r.team_id == home else 1
                events.append((r.minute, diff))
        end = max(90, int(g["minute"].max()))
        minutes_close, last_min, state = 0.0, 0, 0
        for minute, new_state in events:
            if abs(state) <= 1:
                minutes_close += max(minute - last_min, 0)
            last_min, state = minute, new_state
        if abs(state) <= 1:
            minutes_close += max(end - last_min, 0)
        for team in (home, away):
            rate_all = all_xg[team] / end
            if rate_all <= 0:
                factor = 1.0
            else:
                # geglättete Rate bei knappem Spielstand, relativ zur Gesamtrate
                rate_close = (close_xg[team] + rate_all * PRIOR_MINUTES) / (minutes_close + PRIOR_MINUTES)
                factor = rate_close / rate_all
            out.append({"match_id": match_id, "team_id": team, "close_factor": factor})
    return pd.DataFrame(out)


def team_match_xg() -> pd.DataFrame:
    shots = pd.read_sql(SHOTS_SQL, engine)
    stats = pd.read_sql(STATS_SQL, engine)
    pens = shots[shots["situation"] == "Penalty"]
    pen_per_team_match = pens["xg"].sum() / max(len(stats), 1)
    df = stats.merge(_close_factors(shots), on=["match_id", "team_id"], how="left")
    df["close_factor"] = df["close_factor"].fillna(1.0).clip(0.5, 2.0)
    df["npxg"] = df["npxg"].fillna(df["xg"])
    df["npxg_pen"] = df["npxg"] + pen_per_team_match
    df["close"] = df["npxg_pen"] * df["close_factor"]
    df["red"] = df["reds"] > 0
    return df[["match_id", "team_id", "xg", "npxg", "npxg_pen", "close", "close_factor", "red"]]


def apply_variant(matches: pd.DataFrame, variant: str, xg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Ersetzt hxg/axg in der Spieltabelle durch die gewählte Variante und setzt ein Gewicht
    für Spiele mit Roter Karte (Spalte red_any)."""
    xg = xg if xg is not None else team_match_xg()
    df = matches.copy()
    for side, team_col in (("h", "home_id"), ("a", "away_id")):
        part = xg.rename(columns={"team_id": team_col})[["match_id", team_col, variant, "red"]]
        part = part.rename(columns={variant: f"{side}xg_new", "red": f"{side}red"})
        df = df.merge(part, on=["match_id", team_col], how="left")
        df[f"{side}xg"] = df[f"{side}xg_new"].where(df[f"{side}xg_new"].notna(), df[f"{side}xg"])
    df["red_any"] = df["hred"].fillna(False).astype(bool) | df["ared"].fillna(False).astype(bool)
    return df.drop(columns=["hxg_new", "axg_new", "hred", "ared"])
