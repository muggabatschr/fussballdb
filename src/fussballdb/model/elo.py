"""Elo-Wertung mit Tordifferenz-Faktor und Rückführung zum Mittel zwischen den Saisons.
Wahrscheinlichkeiten für 1/X/2 über ein geordnetes Logit auf der Elo-Differenz."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

BASE = 1500.0


@dataclass
class Elo:
    k: float = 20.0
    home_adv: float = 65.0
    season_regression: float = 0.2
    newcomer: float = 1400.0  # Startwert für Teams, die nach der ersten Saison dazukommen

    ratings: dict[int, float] = field(default_factory=dict)

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        """Geht alle Spiele chronologisch durch. Liefert pro Spiel die Elo vor dem Anpfiff
        (für beendete und kommende Spiele) und für beendete Spiele die Werte danach."""
        ratings: dict[int, float] = {}
        first_season = df["season"].min()
        season = None
        out = []
        for r in df.sort_values(["kickoff", "match_id"]).itertuples():
            if r.season != season:
                season = r.season
                ratings = {
                    t: BASE + (v - BASE) * (1 - self.season_regression) for t, v in ratings.items()
                }
            for t in (r.home_id, r.away_id):
                if t not in ratings:
                    ratings[t] = BASE if r.season == first_season else self.newcomer
            rh, ra = ratings[r.home_id], ratings[r.away_id]
            row = {"match_id": r.match_id, "elo_home": rh, "elo_away": ra, "elo_home_after": None, "elo_away_after": None}
            if r.finished and not pd.isna(r.hg):
                exp_h = 1 / (1 + 10 ** (-(rh + self.home_adv - ra) / 400))
                score = 1.0 if r.hg > r.ag else 0.5 if r.hg == r.ag else 0.0
                gd = abs(int(r.hg) - int(r.ag))
                mult = 1 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
                delta = self.k * mult * (score - exp_h)
                ratings[r.home_id] = rh + delta
                ratings[r.away_id] = ra - delta
                row["elo_home_after"] = rh + delta
                row["elo_away_after"] = ra - delta
            out.append(row)
        self.ratings = ratings
        return pd.DataFrame(out)


@dataclass
class EloOutcomeModel:
    """Geordnetes Logit: P(Auswärtssieg) = σ(c1 − b·d), P(Heimsieg) = 1 − σ(c2 − b·d), d = Elo-Differenz/100."""

    home_adv: float = 65.0
    params: np.ndarray = field(default_factory=lambda: np.array([-1.2, 0.3, 0.35]))

    def _diff(self, elo_home, elo_away):
        return (np.asarray(elo_home) + self.home_adv - np.asarray(elo_away)) / 100

    def fit(self, elo_home, elo_away, outcome) -> "EloOutcomeModel":
        d = self._diff(elo_home, elo_away)
        y = np.asarray(outcome)  # 0 = Auswärtssieg, 1 = Remis, 2 = Heimsieg

        def nll(p):
            probs = self._probs(d, p)
            return -np.sum(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, None)))

        self.params = minimize(nll, self.params, method="Nelder-Mead").x
        return self

    @staticmethod
    def _probs(d, p):
        c1, gap, b = p
        c2 = c1 + abs(gap)
        p_away = expit(c1 - b * d)
        p_not_home = expit(c2 - b * d)
        return np.column_stack([p_away, p_not_home - p_away, 1 - p_not_home])

    def predict(self, elo_home, elo_away) -> np.ndarray:
        """Spalten: Auswärtssieg, Remis, Heimsieg."""
        return self._probs(self._diff(elo_home, elo_away), self.params)
