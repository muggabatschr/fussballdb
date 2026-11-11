"""Weitere Teamstatistik der letzten Spiele als Zusatzfaktor auf die Torerwartung, nur für den Rückblick-Test
(fussballdb statistik-test): Schüsse, Schüsse aufs Tor, Großchancen, Ecken, PPDA, Deep (Pässe in die Nähe des
Strafraums), Passquote und Ruhetage. Gleiches Verfahren wie beim Ballbesitz (features/running.py): je Team der
Mittelwert des Unterschieds zum Gegner aus den letzten `window` Bundesligaspielen vor dem Stichtag, geteilt durch die
Streuung dieses Mittelwerts über alle Teams (z-Wert), Faktor exp(beta · z) auf die eigene und exp(−beta · z) auf die
gegnerische Torerwartung. Ruhetage: Tage seit dem letzten Bundesligaspiel (höchstens 14), Unterschied zum Gegner im
Spiel selbst, ebenfalls als z-Wert.

Ergebnis November 2026 (Einstellen 2016–20, Test 2021–26, RPS-Delta gegen das Modell mit Ballbesitz): verworfen,
im Modell ist nichts davon aktiv.
- Einzeln: keine Kennzahl in 90 % der Ziehungen besser und im Einstellzeitraum besser. Schüsse, aufs Tor, Ecken
  +0,03: Einstellen −0,0005, Test −0,0001 bis −0,0002 (65–70 %). Deep +0,03: −0,0003 (80 %). Ruhetage −0,03:
  ±0 / −0,0002 (91 %, 6 von 11 Saisons, mehr Pause = minimal schlechter). Großchancen, PPDA, Passquote: nichts.
- Kombiniert: Ruhetage + Deep −0,0005 (92 %), mit Tor-Skalierung −0,0009 (97 %), aber nach dem Testzeitraum
  ausgewählt, nur 6 von 11 Saisons, Tipp-Punkte nicht besser. Alle Kennzahlen zusammen: +0,0004.
- Alle 255 Teilmengen ohne und mit Tor-Skalierung, Auswahl nur nach dem Einstellzeitraum: ohne Tor-Skalierung
  nichts (−0,0001, 56 %); mit Tor-Skalierung + Schüsse, aufs Tor, Ecken, Ruhetage −0,0007 (91 %). Diese
  Kombination läuft als Alternativtipp mit (model/alt_tip.py) und wird live geprüft."""

import math

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

METRICS = {"schuesse": "shots", "aufs_tor": "shots_on_target", "grosschancen": "big_chances", "ecken": "corners",
           "ppda": "ppda", "deep": "deep", "passquote": "pass_pct"}
REST = "ruhetage"
REST_CAP = 14


class StatForm:
    def __init__(self, window: int = 10):
        self.window = window
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT t.match_id, m.kickoff, t.is_home, t.team_id, t.shots, t.shots_on_target, t.big_chances,
                       t.corners, t.ppda, t.deep, e.pass_pct
                FROM match_team_stats t JOIN match m ON m.id = t.match_id JOIN season s ON s.id = m.season_id
                LEFT JOIN match_extra_stats e ON e.competition = 'BL' AND e.match_id = t.match_id
                                              AND e.is_home = t.is_home
                WHERE s.start_year >= 2014 AND m.home_goals IS NOT NULL"""), conn)
            games = pd.read_sql(text("""
                SELECT m.kickoff, m.home_team_id, m.away_team_id FROM match m"""), conn)
        df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
        cols = list(METRICS.values())
        df[cols] = df[cols].astype(float)
        opp = df[["match_id", "is_home", *cols]].copy()
        opp["is_home"] = ~opp["is_home"]
        df = df.merge(opp, on=["match_id", "is_home"], suffixes=("", "_opp"))
        for col in cols:
            df[col] = df[col] - df[f"{col}_opp"]
        self.games = {t: g.sort_values("kickoff") for t, g in df[["team_id", "kickoff", *cols]].groupby("team_id")}
        rolled = pd.concat([g[cols].rolling(window, min_periods=window // 2).mean() for g in self.games.values()])
        self.scale = rolled.std().to_dict()
        games["kickoff"] = pd.to_datetime(games["kickoff"], utc=True)
        self.played = {t: np.sort(g.dt.tz_localize(None).to_numpy()) for t, g in pd.concat([
            games[["home_team_id", "kickoff"]].rename(columns={"home_team_id": "t"}),
            games[["away_team_id", "kickoff"]].rename(columns={"away_team_id": "t"})]).groupby("t")["kickoff"]}
        self.rest_scale = 3.0  # Streuung des Ruhetage-Unterschieds (Tage), siehe rest_diff
        self._cache: dict[tuple, dict | None] = {}

    def z(self, team: int, cutoff: pd.Timestamp) -> dict[str, float] | None:
        key = (team, cutoff)
        if key not in self._cache:
            g = self.games.get(team)
            g = g[g["kickoff"] < cutoff].tail(self.window) if g is not None else None
            self._cache[key] = None if g is None or len(g) < self.window // 2 else {
                name: float(g[col].mean() / self.scale[col]) if g[col].notna().sum() >= self.window // 2 else math.nan
                for name, col in METRICS.items()}
        return self._cache[key]

    def rest_days(self, team: int, kickoff: pd.Timestamp) -> float:
        k = np.datetime64(pd.Timestamp(kickoff).tz_convert("UTC").tz_localize(None))
        p = self.played.get(team)
        if p is None:
            return REST_CAP
        before = p[p < k - np.timedelta64(1, "h")]
        return REST_CAP if not len(before) else min(REST_CAP, (k - before[-1]) / np.timedelta64(1, "D"))

    def rest_z(self, home: int, away: int, kickoff: pd.Timestamp) -> float:
        """Ruhetage Heim minus Gast, geteilt durch rest_scale (aus Sicht des Heimteams)."""
        return (self.rest_days(home, kickoff) - self.rest_days(away, kickoff)) / self.rest_scale

    @staticmethod
    def apply(impact: dict, z: dict | None, betas: dict[str, float], rest: float = 0.0) -> dict:
        s = 0.0
        if z:
            s += sum(b * z[n] for n, b in betas.items() if n in z and not math.isnan(z[n]))
        s += betas.get(REST, 0.0) * rest
        if s == 0.0:
            return impact
        out = dict(impact)
        out["attack_mult"] = out.get("attack_mult", 1.0) * math.exp(s)
        out["concede_mult"] = out.get("concede_mult", 1.0) * math.exp(-s)
        return out
