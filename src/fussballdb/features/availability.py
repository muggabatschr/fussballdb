"""Wie stark schwächt ein Ausfall ein Team? Grundlage sind die letzten Einsätze (Understat-Kader).

- Angriff: Anteil der fehlenden Spieler an xG + xA des Teams -> Torerwartung sinkt
- Abwehr: fehlende Stamm-Defensivspieler (Torwart, Verteidiger, Sechser) -> Gegentorerwartung steigt
Ein Ersatzspieler fängt einen Teil auf, daher die Dämpfung über beta/gamma.
"""

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

DEFENSIVE_POSITIONS = {"GK", "DR", "DC", "DL", "DMR", "DMC", "DML"}

APPEARANCES_SQL = text(
    """
    SELECT pm.match_id, pm.player_id, p.name, pm.team_id, pm.position, pm.started, pm.minutes,
           pm.xg, pm.xa, pm.red_cards, pm.yellow_cards, m.kickoff, m.season_id
    FROM player_match pm JOIN match m ON m.id = pm.match_id JOIN player p ON p.id = pm.player_id
    ORDER BY m.kickoff, m.id
    """
)


@dataclass
class AvailabilityModel:
    window: int = 8  # letzte N Spiele des Teams
    regular_share: float = 0.5  # Stammspieler: mind. 50 % der möglichen Minuten
    beta: float = 0.5  # wie viel des Offensivanteils wirklich verloren geht (Kombinations-Test)
    gamma: float = 0.06  # Gegentor-Aufschlag je fehlendem Stamm-Defensivspieler
    floor: float = 0.75
    cap: float = 1.2
    max_gap_days: int = 45  # längere Pause = Sommerpause, Kader davor zählt nicht mehr

    def __post_init__(self):
        self.apps = pd.read_sql(APPEARANCES_SQL, engine)
        self.apps["kickoff"] = pd.to_datetime(self.apps["kickoff"], utc=True)
        self.apps["xgxa"] = self.apps["xg"] + self.apps["xa"]

    def player_profile(self, team_id: int, before: pd.Timestamp) -> pd.DataFrame:
        """Pro Spieler: Minutenanteil, Offensivanteil, Stammspieler, Defensivspieler."""
        team = self.apps[(self.apps["team_id"] == team_id) & (self.apps["kickoff"] < before)]
        recent = self._recent_matches(team)
        team = team[team["match_id"].isin(recent)]
        n = max(len(recent), 1)
        prof = team.groupby(["player_id", "name"]).agg(
            minutes=("minutes", "sum"), xgxa=("xgxa", "sum"),
            position=("position", lambda s: s[s != "Sub"].mode().iat[0] if (s != "Sub").any() else "Sub"),
        ).reset_index()
        total = prof["xgxa"].sum() or 1.0
        prof["minute_share"] = prof["minutes"] / (n * 90)
        prof["offense_share"] = prof["xgxa"] / total
        prof["regular"] = prof["minute_share"] >= self.regular_share
        prof["defensive"] = prof["position"].isin(DEFENSIVE_POSITIONS)
        return prof.sort_values("offense_share", ascending=False)

    def impact(self, team_id: int, before: pd.Timestamp, missing_ids: set[int],
               suspended_ids: set[int] | None = None) -> dict:
        """suspended_ids: Teilmenge von missing_ids, die gesperrt ist (nur für die Beschriftung)."""
        prof = self.player_profile(team_id, before)
        miss = prof[prof["player_id"].isin(missing_ids)]
        suspended_ids = suspended_ids or set()
        names = [f"{r.name} (gesperrt)" if r.player_id in suspended_ids else r.name
                 for r in miss[miss["regular"]].itertuples()]
        off = float(miss["offense_share"].sum())
        def_regulars = int((miss["regular"] & miss["defensive"]).sum())
        return {
            "attack_mult": max(self.floor, 1 - self.beta * off),
            "concede_mult": min(self.cap, 1 + self.gamma * def_regulars),
            "missing_offense_share": off,
            "missing_regulars": names,
            "missing_defensive_regulars": def_regulars,
        }

    def _recent_matches(self, team: pd.DataFrame) -> list[int]:
        """Die letzten `window` Spiele eines Teams, chronologisch, ohne über eine Sommerpause zu reichen
        (sonst gelten im Sommer gewechselte Spieler als fehlende Stammspieler)."""
        if team.empty:
            return []
        games = team.drop_duplicates("match_id").sort_values("kickoff")[["match_id", "kickoff"]]
        gaps = games["kickoff"].diff().dt.days.fillna(0)
        breaks = games.index[gaps > self.max_gap_days]
        if len(breaks):
            games = games.loc[breaks[-1]:]
        return games["match_id"].tail(self.window).tolist()

    def injured_as_of(self, team_id: int, cutoff: pd.Timestamp, injuries: pd.DataFrame) -> set[int]:
        """Spieler, die am Stichtag laut Transfermarkt-Historie verletzt gemeldet waren
        (Beginn vor dem Stichtag, Ende danach oder offen). Das spätere Rückkehrdatum wird nur
        genutzt, um zu sehen, ob die Verletzung am Stichtag noch lief."""
        day = cutoff.tz_convert("Europe/Berlin").date()
        inj = injuries[(injuries["team_id"] == team_id) & (injuries["von"] < day)]
        inj = inj[inj["bis"].isna() | (inj["bis"] >= day)]
        return set(inj["player_id"].dropna().astype(int))

    def suspended_as_of(self, team_id: int, cutoff: pd.Timestamp) -> set[int]:
        """Sperren, die zum Stichtag feststanden: Rot/Gelb-Rot im letzten Spiel des Teams oder die
        5./10./15. Gelbe Karte der Saison in diesem Spiel. (Understat unterscheidet Gelb-Rot und Rot
        nicht; längere Sperren nach glatt Rot sind daher nur für das nächste Spiel erfasst.)"""
        team = self.apps[(self.apps["team_id"] == team_id) & (self.apps["kickoff"] < cutoff)]
        if team.empty:
            return set()
        last_kickoff = team["kickoff"].max()
        if cutoff - last_kickoff > pd.Timedelta(days=45):
            return set()  # Sommerpause: Gelbsperren verfallen, Rotsperren aus der Vorsaison selten
        last = team[team["kickoff"] == last_kickoff]
        out = set(last.loc[last["red_cards"] > 0, "player_id"])
        booked = last.loc[last["yellow_cards"] > 0, "player_id"]
        if len(booked):
            season = team[(team["season_id"] == last["season_id"].iat[0]) & team["player_id"].isin(booked)]
            totals = season.groupby("player_id")["yellow_cards"].sum()
            out |= set(totals[(totals > 0) & (totals % 5 == 0)].index)
        return out

    def missing_from_lineup(self, team_id: int, match_id: int, before: pd.Timestamp) -> set[int]:
        """Für den Backtest: Stammspieler, die im Kader dieses Spiels fehlten."""
        prof = self.player_profile(team_id, before)
        regulars = set(prof.loc[prof["regular"], "player_id"])
        in_squad = set(self.apps.loc[(self.apps["match_id"] == match_id) & (self.apps["team_id"] == team_id), "player_id"])
        return regulars - in_squad if in_squad else set()
