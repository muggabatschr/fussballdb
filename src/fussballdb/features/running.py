"""Laufleistung, Sprints, Ballbesitz und Zweikämpfe der letzten Spiele als Zusatzfaktor auf die Torerwartung
(Sportschau-Daten, match_extra_stats, Bundesliga ab 2014/15). Im Modell aktiv ist nur der Ballbesitz
(ACTIVE_BETAS); der Rest ist im Rückblick-Test (fussballdb laufleistung-test) verworfen.

Ergebnis Oktober 2026 (eingestellt 2016–2020, Test 2021–2026, 98 % der Spiele mit Daten beider Teams; RPS-Delta
gegen das Modell ohne Faktor, kleiner = besser):
- Ballbesitz, beta 0,03: −0,0005 im Einstell- und im Testzeitraum, besser in 96 % der Ziehungen, 8 von 11
  Saisons, Tipp-Punkte 1,347 statt 1,335 je Spiel -> übernommen.
- Ballbesitz, beta 0,06: −0,0006 im Test, aber nur 85 % der Ziehungen.
- Kilometer, Sprints, Zweikämpfe einzeln und alle vier zusammen: im Test höchstens −0,0003, meist schlechter.
- Mit den verworfenen Bausteinen (Tor-Skalierung, Duelle, Heimvorteil je Team, Remis-Kalibrierung,
  Halbwertszeit 3 Monate): Tor-Skalierung + Ballbesitz 0,03 kommt auf −0,0010 (98 %), die Tor-Skalierung allein
  ist aber im Einstellzeitraum schlechter; Ballbesitz bringt in jeder Kombination etwa gleich viel.

Je Team und Kennzahl der Mittelwert des Unterschieds zum jeweiligen Gegner (eigene minus gegnerische km, Sprints,
Ballbesitz-Prozentpunkte, Zweikampf-Prozentpunkte) aus den letzten `window` Bundesligaspielen vor dem Stichtag,
geteilt durch die Streuung dieses Mittelwerts über alle Teams (z-Wert). Der Faktor exp(beta · z) hebt die
eigene Torerwartung und senkt die gegnerische (exp(−beta · z))."""

import math

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

METRICS = {"km": "distance_km", "sprints": "sprints", "ballbesitz": "possession", "zweikaempfe": "duels_won_pct"}
ACTIVE_BETAS = {"ballbesitz": 0.03}  # im Modell (predict.py); leer = aus


class RunningForm:
    def __init__(self, window: int = 10):
        self.window = window
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT e.match_id, m.kickoff, e.is_home,
                       CASE WHEN e.is_home THEN m.home_team_id ELSE m.away_team_id END AS team_id,
                       e.distance_km, e.sprints, e.possession, e.duels_won_pct
                FROM match_extra_stats e JOIN match m ON m.id = e.match_id
                WHERE e.competition = 'BL' AND e.distance_km IS NOT NULL"""), conn)
        df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
        df["own_possession"] = df["possession"]
        opp = df[["match_id", "is_home", *METRICS.values()]].copy()
        opp["is_home"] = ~opp["is_home"]
        df = df.merge(opp, on=["match_id", "is_home"], suffixes=("", "_opp"))
        for col in METRICS.values():
            df[col] = df[col] - df[f"{col}_opp"]
        self.games = {t: g.sort_values("kickoff") for t, g in df[["team_id", "kickoff", "own_possession", *METRICS.values()]].groupby("team_id")}
        # Streuung des Mittelwerts über `window` Spiele, aus allen rollenden Mittelwerten
        rolled = pd.concat([g[list(METRICS.values())].rolling(window).mean() for g in self.games.values()])
        self.scale = rolled.std().to_dict()
        self._cache: dict[tuple, dict | None] = {}

    def z(self, team: int, cutoff: pd.Timestamp) -> dict[str, float] | None:
        """z-Wert je Kennzahl aus den letzten Spielen vor `cutoff` (None ohne genug Spiele)."""
        key = (team, cutoff)
        if key not in self._cache:
            g = self.games.get(team)
            g = g[g["kickoff"] < cutoff].tail(self.window) if g is not None else None
            self._cache[key] = None if g is None or len(g) < self.window // 2 else {
                **{name: float(g[col].mean() / self.scale[col]) for name, col in METRICS.items()},
                "ballbesitz_schnitt": float(g["own_possession"].mean()), "spiele": len(g)}
        return self._cache[key]

    @staticmethod
    def apply(impact: dict, z: dict | None, betas: dict[str, float]) -> dict:
        """Ausfall-Wirkung um den Faktor ergänzen: attack_mult × exp(Σ beta · z), concede_mult × exp(−Σ beta · z),
        dazu spielstil = {faktor, ballbesitz, spiele} für die Begründung."""
        if not z or not betas:
            return impact
        s = sum(b * z[name] for name, b in betas.items() if not np.isnan(z[name]))
        out = dict(impact)
        out["attack_mult"] = out.get("attack_mult", 1.0) * math.exp(s)
        out["concede_mult"] = out.get("concede_mult", 1.0) * math.exp(-s)
        out["spielstil"] = {"faktor": math.exp(s), "ballbesitz": z.get("ballbesitz_schnitt"), "spiele": z.get("spiele")}
        return out

    def apply_active(self, impact: dict, team: int, cutoff: pd.Timestamp) -> dict:
        """Den im Modell aktiven Faktor (ACTIVE_BETAS) mit dem Stand vor `cutoff` anwenden."""
        return self.apply(impact, self.z(team, pd.Timestamp(cutoff)), ACTIVE_BETAS) if ACTIVE_BETAS else impact
