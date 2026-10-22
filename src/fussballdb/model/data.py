import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.config import MODEL_FIRST_SEASON
from fussballdb.db.session import engine

MATCHES_SQL = text(
    """
    SELECT m.id AS match_id, m.kickoff, s.start_year AS season, m.matchday,
           m.home_team_id AS home_id, m.away_team_id AS away_id,
           ht.name AS home, at.name AS away,
           m.home_goals AS hg, m.away_goals AS ag, m.finished,
           hs.xg AS hxg, as_.xg AS axg
    FROM match m
    JOIN season s ON s.id = m.season_id
    JOIN team ht ON ht.id = m.home_team_id
    JOIN team at ON at.id = m.away_team_id
    LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
    LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
    WHERE s.start_year >= :first
    ORDER BY m.kickoff, m.id
    """
)

MARKET_SQL = text(
    """
    SELECT match_id, is_closing, home, draw, away
    FROM odds WHERE bookmaker = 'Avg'
    """
)


def load_matches(first_season: int = MODEL_FIRST_SEASON) -> pd.DataFrame:
    """Spiele für das Modell, nur ab MODEL_FIRST_SEASON (ältere Saisons sind nur zur Anzeige da;
    first_season kleiner nur für Tests wie compare_elo_history)."""
    df = pd.read_sql(MATCHES_SQL, engine, params={"first": first_season})
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    return df


def load_market() -> pd.DataFrame:
    """Marktwahrscheinlichkeiten aus Durchschnittsquoten, Buchmachermarge proportional entfernt."""
    df = pd.read_sql(MARKET_SQL, engine)
    inv = 1 / df[["home", "draw", "away"]]
    probs = inv.div(inv.sum(axis=1), axis=0)
    probs.columns = ["p_home", "p_draw", "p_away"]
    return pd.concat([df[["match_id", "is_closing"]], probs], axis=1)


def load_squad_values() -> pd.DataFrame:
    df = pd.read_sql(text("SELECT team_id, stichtag, value_eur FROM squad_value"), engine)
    df["stichtag"] = pd.to_datetime(df["stichtag"]).dt.tz_localize("Europe/Berlin")
    return df


def value_priors(values: pd.DataFrame, matches: pd.DataFrame, cutoff: pd.Timestamp, k: float) -> dict:
    """Startstärke aus dem Kaderwert zum letzten Stichtag vor `cutoff`: z = log(Wert) relativ zum
    Mittel der Teams der Saison, Angriff = k·z, Abwehr = −k·z (positive Abwehr = mehr Gegentore)."""
    if k <= 0 or values.empty:
        return {}
    known = values[values["stichtag"] <= cutoff]
    if known.empty:
        return {}
    latest = known[known["stichtag"] == known["stichtag"].max()].set_index("team_id")["value_eur"]
    upcoming = matches[matches["kickoff"] >= cutoff]
    season = upcoming["season"].iloc[0] if not upcoming.empty else matches["season"].max()
    teams = set(matches.loc[matches["season"] == season, "home_id"])
    logv = np.log(latest[latest.index.isin(teams)])
    if logv.empty:
        return {}
    z = logv - logv.mean()
    return {int(t): (k * float(v), -k * float(v)) for t, v in z.items()}
