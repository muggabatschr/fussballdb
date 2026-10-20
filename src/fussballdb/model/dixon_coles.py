"""Dixon-Coles-Modell: Angriffs-/Abwehrstärke je Team, Heimvorteil, Korrektur für 0:0/1:0/0:1/1:1.

Die Zielgröße ist eine Mischung aus xG und Toren (w_xg). xG ist stabiler als Tore und sagt
künftige Tore besser voraus. Im Rückblick-Test war reines xG am besten (w_xg = 1); npxG und eine
Spielstand-Bereinigung brachten nichts (fussballdb xg-varianten).
Ältere Spiele werden exponentiell abgewertet (xi pro Tag).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10


@dataclass
class DixonColes:
    xi: float = 0.003  # Halbwertszeit ~ 8 Monate (per Backtest gewählt)
    w_xg: float = 1.0
    ridge: float = 5.0  # Dämpfung Richtung Startstärke (zusammen mit dem Kaderwert gewählt)
    # Startwert für Teams ohne Daten (Aufsteiger): schwächer als der Ligaschnitt
    newcomer_att: float = -0.15
    newcomer_def: float = 0.15
    min_matches: int = 6
    red_card_weight: float = 1.0  # Gewicht für Spiele mit Roter Karte (Spalte red_any)
    # Startstärke je Team (z. B. aus dem Kaderwert): team_id -> (Angriff, Abwehr). Ersetzt den
    # Aufsteiger-Prior; die Spiele ziehen die Werte mit wachsender Datenmenge davon weg.
    priors: dict[int, tuple[float, float]] = field(default_factory=dict)
    # Heimvorteil je Team zusätzlich zum gemeinsamen, stark gedämpft (None = aus)
    team_home_ridge: float | None = None
    # Kalibrierung auf echte Tore der Trainingsspiele: Torerwartung je Heim/Gast skalieren
    # (xG liegt etwas über den Toren, der Heimvorteil in xG etwas über dem in Toren) und
    # Unentschieden-Ergebnisse gemeinsam auf- oder abwerten (Poisson unterschätzt Remis)
    goal_scale: bool = False
    draw_inflation: bool = False
    # Remis-Kalibrierung: logit(P_Remis) = a + b·logit(P_Remis laut Modell), auf den Trainingsspielen
    # geschätzt. Hebt Remis dort an, wo das Modell sie systematisch unterschätzt (ausgeglichene Spiele).
    draw_calibration: bool = False

    teams: list[int] = field(default_factory=list)
    mu: float = 0.0
    home_adv: float = 0.0
    att: dict[int, float] = field(default_factory=dict)
    defence: dict[int, float] = field(default_factory=dict)
    rho: float = 0.0
    team_home: dict[int, float] = field(default_factory=dict)
    scale_home: float = 1.0
    scale_away: float = 1.0
    draw_boost: float = 0.0  # log-Faktor auf alle Diagonal-Ergebnisse
    draw_cal: tuple[float, float] | None = None  # (a, b) der Remis-Kalibrierung

    def fit(self, df: pd.DataFrame, now: pd.Timestamp | None = None) -> "DixonColes":
        df = df[df["finished"]].dropna(subset=["hg", "ag"])
        now = now or df["kickoff"].max()
        teams = sorted(set(df["home_id"]) | set(df["away_id"]))
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        h = df["home_id"].map(idx).to_numpy()
        a = df["away_id"].map(idx).to_numpy()
        hxg = df["hxg"].fillna(df["hg"]).to_numpy(float)
        axg = df["axg"].fillna(df["ag"]).to_numpy(float)
        yh = self.w_xg * hxg + (1 - self.w_xg) * df["hg"].to_numpy(float)
        ya = self.w_xg * axg + (1 - self.w_xg) * df["ag"].to_numpy(float)
        days = (now - df["kickoff"]).dt.total_seconds().to_numpy() / 86400
        w = np.exp(-self.xi * np.clip(days, 0, None))
        if "red_any" in df and self.red_card_weight != 1.0:
            w = w * np.where(df["red_any"].to_numpy(bool), self.red_card_weight, 1.0)

        # Teams mit wenig Spielen werden zum Aufsteiger-Prior gezogen, die anderen zu 0
        counts = np.bincount(h, minlength=n) + np.bincount(a, minlength=n)
        few = counts < self.min_matches
        att0 = np.where(few, self.newcomer_att, 0.0)
        def0 = np.where(few, self.newcomer_def, 0.0)
        for t, i in idx.items():
            if t in self.priors:
                att0[i], def0[i] = self.priors[t]

        th_ridge = self.team_home_ridge
        n_home = n if th_ridge is not None else 0

        def loss(p):
            mu, home, att, dfn = p[0], p[1], p[2 : 2 + n], p[2 + n : 2 + 2 * n]
            hh = p[2 + 2 * n :] if n_home else np.zeros(n)
            lh = np.exp(mu + home + hh[h] + att[h] + dfn[a])
            la = np.exp(mu + att[a] + dfn[h])
            nll = -np.sum(w * (yh * np.log(lh) - lh + ya * np.log(la) - la))
            pen = self.ridge * (np.sum((att - att0) ** 2) + np.sum((dfn - def0) ** 2))
            rh = w * (lh - yh)
            ra = w * (la - ya)
            g = np.empty_like(p)
            g[0] = rh.sum() + ra.sum()
            g[1] = rh.sum()
            g[2 : 2 + n] = np.bincount(h, rh, n) + np.bincount(a, ra, n) + 2 * self.ridge * (att - att0)
            g[2 + n : 2 + 2 * n] = np.bincount(a, rh, n) + np.bincount(h, ra, n) + 2 * self.ridge * (dfn - def0)
            if n_home:
                pen += th_ridge * np.sum(hh ** 2)
                g[2 + 2 * n :] = np.bincount(h, rh, n) + 2 * th_ridge * hh
            return nll + pen, g

        x0 = np.concatenate([[np.log(1.4), 0.2], att0, def0, np.zeros(n_home)])
        res = minimize(loss, x0, jac=True, method="L-BFGS-B")
        p = res.x
        self.teams = teams
        self.mu, self.home_adv = float(p[0]), float(p[1])
        self.att = {t: float(p[2 + i]) for t, i in idx.items()}
        self.defence = {t: float(p[2 + n + i]) for t, i in idx.items()}
        hh = p[2 + 2 * n :] if n_home else np.zeros(n)
        self.team_home = {t: float(hh[i]) for t, i in idx.items()} if n_home else {}

        # rho auf den echten Toren schätzen
        lh = np.exp(self.mu + self.home_adv + hh[h] + p[2 + h] + p[2 + n + a])
        la = np.exp(self.mu + p[2 + a] + p[2 + n + h])
        hg = df["hg"].to_numpy(int)
        ag = df["ag"].to_numpy(int)
        self.scale_home = self.scale_away = 1.0
        if self.goal_scale:
            self.scale_home = float(np.sum(w * hg) / np.sum(w * lh))
            self.scale_away = float(np.sum(w * ag) / np.sum(w * la))
            lh, la = lh * self.scale_home, la * self.scale_away

        def rho_loss(rho):
            t = _tau(hg, ag, lh, la, rho)
            return -np.sum(w * np.log(np.clip(t, 1e-10, None)))

        self.rho = float(minimize_scalar(rho_loss, bounds=(-0.2, 0.2), method="bounded").x)

        self.draw_boost = 0.0
        self.draw_cal = None
        if self.draw_calibration:
            k = np.arange(MAX_GOALS + 1)
            diag = poisson.pmf(k[None, :], lh[:, None]) * poisson.pmf(k[None, :], la[:, None])
            diag[:, 0] *= 1 - lh * la * self.rho
            diag[:, 1] *= 1 - self.rho
            x = _logit(np.clip(diag.sum(1), 1e-4, 1 - 1e-4))
            y = (hg == ag).astype(float)

            def cal_loss(p):
                q = 1 / (1 + np.exp(-(p[0] + p[1] * x)))
                nll = -np.sum(w * (y * np.log(q) + (1 - y) * np.log(1 - q)))
                g = np.array([np.sum(w * (q - y)), np.sum(w * (q - y) * x)])
                return nll, g

            res_cal = minimize(cal_loss, np.array([0.0, 1.0]), jac=True, method="L-BFGS-B",
                               bounds=[(-1.5, 1.5), (0.3, 2.0)])
            self.draw_cal = (float(res_cal.x[0]), float(res_cal.x[1]))
        if self.draw_inflation:
            # P(Remis) je Spiel unter dem bisherigen Modell; Likelihood mit Faktor e^δ auf der Diagonale:
            # δ·1{Remis} − log(1 + (e^δ − 1)·P(Remis))
            k = np.arange(MAX_GOALS + 1)
            ph = poisson.pmf(k[None, :], lh[:, None])
            pa = poisson.pmf(k[None, :], la[:, None])
            diag = ph * pa
            diag[:, 0] *= 1 - lh * la * self.rho
            diag[:, 1] *= 1 - self.rho
            # die Dixon-Coles-Korrektur ändert die Gesamtsumme kaum (<1 %), daher ohne Neunormierung
            p_draw = np.clip(diag.sum(1), 1e-6, 1 - 1e-6)
            is_draw = (hg == ag).astype(float)

            def draw_loss(d):
                return -np.sum(w * (d * is_draw - np.log1p((np.exp(d) - 1) * p_draw)))

            self.draw_boost = float(minimize_scalar(draw_loss, bounds=(-0.5, 0.5), method="bounded").x)
        return self

    def _strength(self, team_id: int) -> tuple[float, float]:
        if team_id in self.att:
            return self.att[team_id], self.defence[team_id]
        return self.priors.get(team_id, (self.newcomer_att, self.newcomer_def))

    def rates(self, home_id: int, away_id: int) -> tuple[float, float]:
        ah, dh = self._strength(home_id)
        aa, da = self._strength(away_id)
        home = self.home_adv + self.team_home.get(home_id, 0.0)
        return (float(np.exp(self.mu + home + ah + da)) * self.scale_home,
                float(np.exp(self.mu + aa + dh)) * self.scale_away)

    def score_matrix(self, home_id: int, away_id: int, adj: tuple[float, float] = (1.0, 1.0)) -> np.ndarray:
        lh, la = self.rates(home_id, away_id)
        lh, la = lh * adj[0], la * adj[1]
        g = np.arange(MAX_GOALS + 1)
        m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
        m[0, 0] *= 1 - lh * la * self.rho
        m[0, 1] *= 1 + lh * self.rho
        m[1, 0] *= 1 + la * self.rho
        m[1, 1] *= 1 - self.rho
        if self.draw_boost:
            m[np.diag_indices_from(m)] *= np.exp(self.draw_boost)
        m = m / m.sum()
        if self.draw_cal is not None:
            p_draw = np.trace(m)
            a, b = self.draw_cal
            target = 1 / (1 + np.exp(-(a + b * _logit(np.clip(p_draw, 1e-4, 1 - 1e-4)))))
            d = np.diag_indices_from(m)
            off = np.ones_like(m, dtype=bool)
            off[d] = False
            m[d] *= target / p_draw
            m[off] *= (1 - target) / (1 - p_draw)
        return m

    def predict(self, home_id: int, away_id: int, adj: tuple[float, float] = (1.0, 1.0)) -> dict:
        """adj: Faktoren auf die Torerwartung (Heim, Gast), z. B. wegen Ausfällen."""
        m = self.score_matrix(home_id, away_id, adj)
        lh, la = self.rates(home_id, away_id)
        lh, la = lh * adj[0], la * adj[1]
        g = np.arange(MAX_GOALS + 1)
        total = g[:, None] + g[None, :]
        top = np.dstack(np.unravel_index(np.argsort(m, axis=None)[::-1][:5], m.shape))[0]
        return {
            "p_home": float(np.tril(m, -1).sum()),
            "p_draw": float(np.trace(m)),
            "p_away": float(np.triu(m, 1).sum()),
            "exp_home_goals": lh,
            "exp_away_goals": la,
            "p_over25": float(m[total > 2.5].sum()),
            "p_btts": float(m[1:, 1:].sum()),
            "top_scores": [(int(i), int(j), float(m[i, j])) for i, j in top],
        }


def _tau(x, y, lh, la, rho):
    t = np.ones_like(lh)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


def _logit(p):
    return np.log(p / (1 - p))
