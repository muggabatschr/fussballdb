"""Kombiniert Dixon-Coles (xG/Tore) und Elo zu einer Prognose je Spiel."""

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from fussballdb.config import TIPP_PUNKTE
from fussballdb.model.data import load_squad_values, value_priors
from fussballdb.model.dixon_coles import DixonColes
from fussballdb.model.elo import Elo, EloOutcomeModel

MODEL_VERSION = "dc-elo-avail-v1"  # Name bleibt, damit gespeicherte Live-Prognosen erhalten bleiben


@dataclass
class Forecaster:
    alpha: float = 0.7  # Gewicht Dixon-Coles, Rest Elo
    dc: DixonColes = field(default_factory=DixonColes)
    elo: Elo = field(default_factory=Elo)
    elo_outcome: EloOutcomeModel = field(default_factory=EloOutcomeModel)
    elo_table: pd.DataFrame | None = None
    # Kaderwert als Startstärke: hilft am Saisonanfang (Spieltag 1–8), danach übernehmen die Spiele.
    # k = 0,2 im Rückblick-Test 2024–2026 (fussballdb kaderwert-test); stärker schadet bei Aufsteigern.
    value_k: float = 0.2
    values: pd.DataFrame | None = None  # Kaderwerte; None = aus der Datenbank laden
    value_newcomers_only: bool = False  # Kaderwert nur für Teams mit wenigen Spielen (Aufsteiger)
    # Formkomponente: zweites Dixon-Coles mit kurzer Halbwertszeit, Torerwartung geometrisch gemischt
    # aktiv seit dem Kombinations-Test 2016–2026 (fussballdb kombi-test): zusammen mit der
    # Verletzten-Korrektur besser in 99 % der Bootstrap-Ziehungen, Form allein in 7 von 11 Saisons
    form_weight: float = 0.4  # 0 = aus
    form_xi: float = 0.02  # ~35 Tage Halbwertszeit
    # Direkte Duelle: Faktor (Σ xG + c) / (Σ erwartete xG + c) aus früheren Duellen (0 = aus)
    h2h_c: float = 0.0
    dc_form: DixonColes | None = None
    train: pd.DataFrame | None = None

    def fit(self, df: pd.DataFrame, cutoff: pd.Timestamp) -> "Forecaster":
        """Trainiert nur mit Spielen, die vor `cutoff` beendet waren (Kaderwert: letzter Stichtag davor)."""
        if self.value_k > 0 and self.values is None:
            self.values = load_squad_values()
        if self.value_k > 0:
            priors = value_priors(self.values, df, cutoff, self.value_k)
            if self.value_newcomers_only:
                played = df[df["finished"] & (df["kickoff"] < cutoff)]
                counts = pd.concat([played["home_id"], played["away_id"]]).value_counts()
                priors = {t: v for t, v in priors.items() if counts.get(t, 0) < self.dc.min_matches}
            self.dc.priors = priors
        known = df.copy()
        later = known["kickoff"] >= cutoff
        known.loc[later, "finished"] = False
        known.loc[later, ["hg", "ag", "hxg", "axg"]] = np.nan
        train = known[known["finished"]]
        self.dc.fit(train, now=cutoff)
        self.train, self.cutoff = train, cutoff
        if self.form_weight > 0:
            self.dc_form = replace(self.dc, xi=self.form_xi, team_home={}).fit(train, now=cutoff)
        self.elo_table = self.elo.run(known).set_index("match_id")
        played = self.elo_table.loc[train["match_id"]]
        outcome = np.sign(train["hg"].to_numpy() - train["ag"].to_numpy()).astype(int) + 1
        self.elo_outcome.home_adv = self.elo.home_adv
        self.elo_outcome.fit(played["elo_home"], played["elo_away"], outcome)
        return self

    def predict_match(self, home_id: int, away_id: int, match_id: int | None = None,
                      home_impact: dict | None = None, away_impact: dict | None = None) -> dict:
        """home_impact/away_impact: Ergebnis von AvailabilityModel.impact (Ausfälle)."""
        hi = home_impact or {"attack_mult": 1.0, "concede_mult": 1.0}
        ai = away_impact or {"attack_mult": 1.0, "concede_mult": 1.0}
        adj = (hi["attack_mult"] * ai["concede_mult"], ai["attack_mult"] * hi["concede_mult"])
        form = (1.0, 1.0)
        if self.dc_form is not None and self.form_weight > 0:
            lh, la = self.dc.rates(home_id, away_id)
            fh, fa = self.dc_form.rates(home_id, away_id)
            form = ((fh / lh) ** self.form_weight, (fa / la) ** self.form_weight)
            adj = (adj[0] * form[0], adj[1] * form[1])
        if self.h2h_c > 0:
            adj = (adj[0] * self._h2h_factor(home_id, away_id), adj[1] * self._h2h_factor(away_id, home_id))
        out = self.dc.predict(home_id, away_id, adj)
        out["adjustment"] = {"home_goals_factor": adj[0], "away_goals_factor": adj[1]}
        if match_id is not None and self.elo_table is not None and match_id in self.elo_table.index:
            eh, ea = self.elo_table.loc[match_id, ["elo_home", "elo_away"]]
        else:
            eh = self.elo.ratings.get(home_id, self.elo.newcomer)
            ea = self.elo.ratings.get(away_id, self.elo.newcomer)
        p_away, p_draw, p_home = self.elo_outcome.predict([eh], [ea])[0]
        out["dc"] = {k: out[k] for k in ("p_home", "p_draw", "p_away")}
        out["elo"] = {"p_home": float(p_home), "p_draw": float(p_draw), "p_away": float(p_away),
                      "elo_home": float(eh), "elo_away": float(ea)}
        for k, v in (("p_home", p_home), ("p_draw", p_draw), ("p_away", p_away)):
            out[k] = self.alpha * out[k] + (1 - self.alpha) * float(v)
        # Tipp mit den meisten erwarteten Punkten nach der Punkteregel der Tipprunde (config.TIPP_PUNKTE)
        out["tip_options"] = tip_options(self.dc.score_matrix(home_id, away_id, adj), out)
        out["tip"] = out["tip_options"][0][0]
        # Einfluss von Form und Ausfällen auf die erwartete Torzahl (für die Begründung)
        out["form"] = {"home": form[0], "away": form[1]}
        out["impact"] = {"home": hi, "away": ai}
        return out


    def _h2h_factor(self, team: int, opponent: int) -> float:
        """Wie viel xG hat `team` in früheren Duellen gegen `opponent` erzeugt, verglichen mit dem,
        was das Modell mit den heutigen Stärken erwarten würde? Gedämpft über h2h_c (in xG)."""
        t = self.train
        past = t[((t["home_id"] == team) & (t["away_id"] == opponent)) | ((t["home_id"] == opponent) & (t["away_id"] == team))]
        if past.empty:
            return 1.0
        w = np.exp(-self.dc.xi * (self.cutoff - past["kickoff"]).dt.days.to_numpy())
        actual, expected = 0.0, 0.0
        for r, wi in zip(past.itertuples(), w):
            lh, la = self.dc.rates(r.home_id, r.away_id)
            if r.home_id == team:
                actual += wi * (r.hxg if not pd.isna(r.hxg) else r.hg)
                expected += wi * lh
            else:
                actual += wi * (r.axg if not pd.isna(r.axg) else r.ag)
                expected += wi * la
        return float((actual + self.h2h_c) / (expected + self.h2h_c))


def kicktipp_points(tip_h: int, tip_a: int, h: int, a: int, rule: tuple[int, int, int, int] = TIPP_PUNKTE) -> int:
    """Punkte nach `rule` = (Sieg Tendenz, Sieg Tordifferenz, exakt, Remis Tendenz)."""
    win_tendency, win_diff, exact, draw_tendency = rule
    if tip_h == h and tip_a == a:
        return exact
    if np.sign(tip_h - tip_a) != np.sign(h - a):
        return 0
    if h == a:
        return draw_tendency
    return win_diff if tip_h - tip_a == h - a else win_tendency


MAX_TIP_GOALS = 5
# Punkte-Tabelle: _POINTS[th, ta, h, a] für alle Tipps und Ergebnisse bis MAX_GOALS
_G = 11
def points_table(rule: tuple[int, int, int, int] = TIPP_PUNKTE) -> np.ndarray:
    return np.array([[[[kicktipp_points(th, ta, h, a, rule) for a in range(_G)] for h in range(_G)]
                      for ta in range(MAX_TIP_GOALS + 1)] for th in range(MAX_TIP_GOALS + 1)], dtype=float)


_POINTS = points_table()


def aligned_matrix(matrix: np.ndarray, probs: dict) -> np.ndarray:
    """Ergebnismatrix so skalieren, dass Heim/Remis/Gast den Ensemble-Wahrscheinlichkeiten entsprechen."""
    i, j = np.indices(matrix.shape)
    out = matrix.copy()
    for mask, key in ((i > j, "p_home"), (i == j, "p_draw"), (i < j, "p_away")):
        total = matrix[mask].sum()
        if total > 0:
            out[mask] *= probs[key] / total
    return out / out.sum()


def tip_options(matrix: np.ndarray, probs: dict, table: np.ndarray | None = None,
                n: int = 3) -> list[tuple[tuple[int, int], float]]:
    """Die n Tipps mit den meisten erwarteten Punkten, plus der beste Remis-Tipp, falls er nicht dabei ist."""
    m = aligned_matrix(matrix, probs)
    table = _POINTS if table is None else table
    expected = np.tensordot(table[:, :, : m.shape[0], : m.shape[1]], m, axes=([2, 3], [0, 1]))
    order = np.argsort(expected, axis=None)[::-1]
    opts = [((int(h), int(a)), float(expected[h, a])) for h, a in (np.unravel_index(i, expected.shape) for i in order[:n])]
    if not any(t[0] == t[1] for t, _ in opts):
        d = int(np.argmax(np.diag(expected)))
        opts.append(((d, d), float(expected[d, d])))
    return opts


def tip_expected_points(matrix: np.ndarray, probs: dict, table: np.ndarray | None = None) -> tuple[int, int]:
    """Tipp mit den meisten erwarteten Punkten (nach der Punkteregel) über alle möglichen Ergebnisse."""
    return tip_options(matrix, probs, table, n=1)[0][0]


def tip(matrix: np.ndarray, probs: dict) -> tuple[int, int]:
    """Früherer Tipp (nur noch zum Vergleich in compare_tips): wahrscheinlichste Tendenz laut
    Ensemble, darin das wahrscheinlichste Ergebnis.
    (Das insgesamt häufigste Ergebnis wäre fast immer 1:1, das bringt im Tippspiel wenig.)"""
    tendency = max(("p_home", "p_draw", "p_away"), key=probs.get)
    i, j = np.indices(matrix.shape)
    mask = {"p_home": i > j, "p_draw": i == j, "p_away": i < j}[tendency]
    flat = np.where(mask, matrix, -1).argmax()
    h, a = np.unravel_index(flat, matrix.shape)
    return int(h), int(a)
