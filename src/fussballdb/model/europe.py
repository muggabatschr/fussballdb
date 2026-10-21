"""Prognosemodell für die Champions League.

Für die Bundesliga gibt es xG, Kader und Ausfälle. Für Europa fehlt das für viele Ligen, und Teams aus
verschiedenen Ländern spielen selten gegeneinander. Deshalb:

1. **Europaweite Elo** über alle Ligaspiele (football-data, 18 Ligen) und Europapokalspiele. Ein Team
   startet bei seinem ersten Spiel mit einer Elo aus seinem Kaderwert (Transfermarkt). So sind die Ligen
   von Anfang an vergleichbar; Europapokalspiele verschieben die Werte danach zwischen den Ländern.
   Zu jeder neuen Saison wird die Elo ein Stück zum Kaderwert zurückgezogen (Transfers im Sommer).
2. **Elo-Tormodell** (Poisson mit Dixon-Coles-Korrektur): erwartete Tore aus Elo-Differenz und
   Heimvorteil (Finale ohne). Die Gewichte werden vor jedem Spieltag nur aus früheren Spielen geschätzt.
3. **xG-Modell** (seit Oktober 2026, ACTIVE_XG): Dixon-Coles wie in der Bundesliga über alle Liga- und
   Europapokalspiele, Zielgröße xG (fünf große Ligen von Understat, CL von FotMob), sonst Tore, Startstärke
   aus dem Kaderwert, dazu eine Formkomponente (40 %, Halbwertszeit 5 Wochen). Die Wahrscheinlichkeiten
   sind zu 70 % xG-Modell und zu 30 % Elo-Tormodell. Im Rückblick-Test (fussballdb cl-xg-test) 2024/25 und
   2025/26 besser als die Elo allein, in den ersten 45 Spielen 2026/27 schlechter; nach der Ligaphase
   2026/27 erneut prüfen.
4. **Tipp** wie in der Bundesliga: das Ergebnis mit den meisten erwarteten Punkten nach der Punkteregel.

Alle Prognosen im Rückblick nutzen nur Spiele und Kaderwerte vor dem ersten Anpfiff des Spieltags.
"""

import bisect
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
from sqlalchemy import text

from fussballdb.db.session import engine
from fussballdb.model.ensemble import kicktipp_points, tip_options

MODEL_VERSION = "eu-xg-elo-v1"
# Kaderwert-Verhältnis als eigenes Merkmal im Tormodell brachte im Rückblick nichts (er steckt schon im
# Startwert und im Saison-Rückzug der Elo), deshalb aus. `fussballdb cl-test` vergleicht beide Varianten.
USE_VALUE = False
EURO = ("CL", "EL")
MAX_GOALS = 10


@dataclass
class EloConfig:
    base: float = 1500.0  # Elo bei einem Kaderwert von 50 Mio. €
    per_log_value: float = 150.0  # Elo-Punkte je Verdopplung des Kaderwerts ≈ 104
    k_league: float = 20.0
    k_euro: float = 30.0
    home: float = 65.0
    season_pull: float = 0.33  # Anteil, um den die Elo zum Saisonstart Richtung Kaderwert rückt
    burn_in: str = "2023-07-01"  # Spiele davor nur zum Einschwingen, nicht zum Schätzen des Tormodells


def load_matches() -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT m.id, m.competition, m.season, m.round_no, m.round_name, m.kickoff, m.home_id, m.away_id,
                   m.home_goals, m.away_goals, m.finished, m.neutral, th.name AS home, ta.name AS away,
                   th.country AS home_country, ta.country AS away_country, m.home_xg, m.away_xg
            FROM eu_match m JOIN eu_team th ON th.id = m.home_id JOIN eu_team ta ON ta.id = m.away_id
            ORDER BY m.kickoff, m.id"""), conn)
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    return df


def load_values() -> dict[int, tuple[list, list]]:
    """Team -> (Stichtage, Kaderwerte) aufsteigend sortiert."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT team_id, stichtag, value_eur FROM eu_squad_value ORDER BY team_id, stichtag")).all()
    out: dict[int, tuple[list, list]] = {}
    for team, day, value in rows:
        days, values = out.setdefault(team, ([], []))
        days.append(pd.Timestamp(day, tz="UTC"))
        values.append(value)
    return out


def value_at(values: dict, team: int, when: pd.Timestamp) -> float | None:
    """Letzter Kaderwert vor `when`."""
    if team not in values:
        return None
    days, vals = values[team]
    i = bisect.bisect_right(days, when) - 1
    return vals[i] if i >= 0 else None


def season_of(ts: pd.Timestamp) -> int:
    return ts.year if ts.month >= 7 else ts.year - 1


@dataclass
class EloState:
    """Elo aller Teams nach jedem Spiel; history erlaubt den Stand zu jedem Zeitpunkt."""

    config: EloConfig
    rating: dict[int, float] = field(default_factory=dict)
    history: dict[int, tuple[list, list]] = field(default_factory=dict)
    pre: dict[int, tuple[float, float]] = field(default_factory=dict)  # match_id -> Elo vor dem Spiel
    season: dict[int, int] = field(default_factory=dict)

    def value_rating(self, value: float) -> float:
        return self.config.base + self.config.per_log_value * math.log(value / 50e6)

    def at(self, team: int, when: pd.Timestamp) -> float | None:
        if team not in self.history:
            return None
        times, ratings = self.history[team]
        i = bisect.bisect_left(times, when) - 1
        return ratings[i] if i >= 0 else None


def run_elo(df: pd.DataFrame, values: dict, config: EloConfig | None = None) -> EloState:
    cfg = config or EloConfig()
    st = EloState(cfg)
    by_comp: dict[str, set[int]] = {}
    for m in df[df["finished"]].itertuples():
        for team, comp in ((m.home_id, m.competition), (m.away_id, m.competition)):
            v = value_at(values, team, m.kickoff)
            season = season_of(m.kickoff)
            if team not in st.rating:
                if v:
                    st.rating[team] = st.value_rating(v)
                else:
                    # ohne Kaderwert: unteres Viertel der Liga, sonst klar unter dem Durchschnitt
                    peers = [st.rating[t] for t in by_comp.get(comp, ()) if t in st.rating]
                    st.rating[team] = float(np.percentile(peers, 25)) if len(peers) >= 5 else cfg.base - 150
                st.season[team] = season
            elif st.season.get(team) != season:
                if v and cfg.season_pull:
                    st.rating[team] += cfg.season_pull * (st.value_rating(v) - st.rating[team])
                st.season[team] = season
            if comp not in EURO:
                by_comp.setdefault(comp, set()).add(team)
        rh, ra = st.rating[m.home_id], st.rating[m.away_id]
        st.pre[m.id] = (rh, ra)
        home = 0.0 if m.neutral else cfg.home
        expected = 1 / (1 + 10 ** (-(rh + home - ra) / 400))
        diff = m.home_goals - m.away_goals
        score = 1.0 if diff > 0 else 0.5 if diff == 0 else 0.0
        margin = 1.0 if abs(diff) <= 1 else 1.5 if abs(diff) == 2 else (11 + abs(diff)) / 8
        k = cfg.k_euro if m.competition in EURO else cfg.k_league
        delta = k * margin * (score - expected)
        st.rating[m.home_id] = rh + delta
        st.rating[m.away_id] = ra - delta
        for team in (m.home_id, m.away_id):
            times, ratings = st.history.setdefault(team, ([], []))
            times.append(m.kickoff)
            ratings.append(st.rating[team])
    return st


# --- Tormodell ---------------------------------------------------------------------------------------

PARAMS = ("mu", "b_elo", "c_value", "home_league", "home_euro", "rho")


def _features(df: pd.DataFrame, st: EloState, values: dict) -> pd.DataFrame:
    """Elo-Differenz (in 400er-Einheiten) und log. Kaderwert-Verhältnis je Spiel, Stand vor dem Spiel."""
    elo_d, val_d = [], []
    for m in df.itertuples():
        pre = st.pre.get(m.id)
        if pre is None:
            rh, ra = st.at(m.home_id, m.kickoff), st.at(m.away_id, m.kickoff)
        else:
            rh, ra = pre
        vh, va = value_at(values, m.home_id, m.kickoff), value_at(values, m.away_id, m.kickoff)
        elo_d.append((rh - ra) / 400 if rh is not None and ra is not None else np.nan)
        val_d.append(math.log(vh / va) if vh and va else np.nan)
    out = df.copy()
    out["elo_d"], out["val_d"] = elo_d, val_d
    return out


def _rates(p: dict, elo_d, val_d, home_flag, euro_flag):
    val_d = np.nan_to_num(val_d)
    h = home_flag * np.where(euro_flag, p["home_euro"], p["home_league"])
    lh = np.exp(p["mu"] + h + p["b_elo"] * elo_d + p["c_value"] * val_d)
    la = np.exp(p["mu"] - p["b_elo"] * elo_d - p["c_value"] * val_d)
    return lh, la


def _tau(x, y, lh, la, rho):
    t = np.ones_like(lh)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return np.clip(t, 1e-6, None)


@dataclass
class GoalModel:
    params: dict

    @classmethod
    def fit(cls, train: pd.DataFrame, use_elo: bool = True, use_value: bool = True) -> "GoalModel":
        # beim Kaderwert-Merkmal nur Spiele, für die beide Werte bekannt sind (Absteiger fehlen bei Transfermarkt)
        train = train.dropna(subset=["elo_d", "val_d"] if use_value else ["elo_d"])
        x, y = train["home_goals"].to_numpy(), train["away_goals"].to_numpy()
        home_flag = (~train["neutral"]).to_numpy(float)
        euro_flag = train["competition"].isin(EURO).to_numpy()
        elo_d, val_d = train["elo_d"].to_numpy(), train["val_d"].to_numpy()
        free = [p for p in PARAMS if (p != "b_elo" or use_elo) and (p != "c_value" or use_value)]

        def nll(theta):
            p = dict.fromkeys(PARAMS, 0.0) | dict(zip(free, theta))
            lh, la = _rates(p, elo_d, val_d, home_flag, euro_flag)
            ll = poisson.logpmf(x, lh) + poisson.logpmf(y, la) + np.log(_tau(x, y, lh, la, p["rho"]))
            return -ll.sum()

        start = {"mu": 0.3, "b_elo": 0.8, "c_value": 0.1, "home_league": 0.15, "home_euro": 0.15, "rho": -0.05}
        res = minimize(nll, [start[p] for p in free], method="L-BFGS-B",
                       bounds=[(-0.3, 0.3) if p == "rho" else (None, None) for p in free])
        return cls(dict.fromkeys(PARAMS, 0.0) | dict(zip(free, res.x)))

    def matrix(self, elo_d: float, val_d: float, neutral: bool, euro: bool = True) -> np.ndarray:
        lh, la = _rates(self.params, np.array([elo_d]), np.array([val_d]), np.array([0.0 if neutral else 1.0]),
                        np.array([euro]))
        lh, la = float(lh[0]), float(la[0])
        g = np.arange(MAX_GOALS + 1)
        m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
        rho = self.params["rho"]
        m[0, 0] *= 1 - lh * la * rho
        m[0, 1] *= 1 + lh * rho
        m[1, 0] *= 1 + la * rho
        m[1, 1] *= 1 - rho
        return m / m.sum()


def probs_from(m: np.ndarray) -> dict:
    i, j = np.indices(m.shape)
    return {"p_home": float(m[i > j].sum()), "p_draw": float(np.trace(m)), "p_away": float(m[i < j].sum()),
            "exp_home": float((m.sum(axis=1) * np.arange(m.shape[0])).sum()),
            "exp_away": float((m.sum(axis=0) * np.arange(m.shape[1])).sum())}


# --- Prognosen ---------------------------------------------------------------------------------------

def all_features(df: pd.DataFrame, st: EloState, values: dict) -> pd.DataFrame:
    """Merkmale aller gespielten Spiele nach dem Einschwingen (einmal berechnen, dann je Stichtag filtern)."""
    done = df[df["finished"] & (df["kickoff"] >= pd.Timestamp(st.config.burn_in, tz="UTC"))]
    return _features(done, st, values)


def predict_round(feats: pd.DataFrame, st: EloState, values: dict, cutoff: pd.Timestamp, matches: pd.DataFrame,
                  use_elo: bool = True, use_value: bool = True, train_years: float = 3.0,
                  xg_model: "XgModel | None" = None) -> list[dict]:
    """Prognosen für `matches` mit dem Stand vor `cutoff`. Das Tormodell sieht nur Spiele davor.
    Mit xg_model werden dessen Wahrscheinlichkeiten mit dem Elo-Modell gemischt (Anteil cfg.alpha)."""
    hist = feats[(feats["kickoff"] < cutoff) & (feats["kickoff"] >= cutoff - pd.Timedelta(days=365 * train_years))]
    model = GoalModel.fit(hist, use_elo, use_value)
    out = []
    for m in matches.itertuples():
        rh, ra = st.at(m.home_id, cutoff), st.at(m.away_id, cutoff)
        vh, va = value_at(values, m.home_id, cutoff), value_at(values, m.away_id, cutoff)
        rh = rh if rh is not None else (st.value_rating(vh) if vh else st.config.base - 150)
        ra = ra if ra is not None else (st.value_rating(va) if va else st.config.base - 150)
        elo_d = (rh - ra) / 400
        val_d = math.log(vh / va) if vh and va else 0.0
        mat = model.matrix(elo_d, val_d, bool(m.neutral), m.competition in EURO)
        p = probs_from(mat)
        form = None
        if xg_model is not None:
            a = xg_model.cfg.alpha
            xmat = xg_model.matrix(m.home_id, m.away_id, bool(m.neutral))
            xp = probs_from(xmat)
            p = {k: a * xp[k] + (1 - a) * p[k] for k in p}
            mat = xmat if a >= 0.5 else mat
            form = xg_model.form_factors(m.home_id, m.away_id)
        opts = tip_options(mat, p)
        out.append({"match_id": m.id, **p, "elo_home": rh, "elo_away": ra, "value_home": vh, "value_away": va,
                    "tip": opts[0][0], "tip_options": opts, "params": model.params, "form": form})
    return out


# --- xG-Modell (Dixon-Coles über ganz Europa) -----------------------------------------------------------

@dataclass
class XgConfig:
    """Dixon-Coles wie in der Bundesliga, über alle Liga- und Europapokalspiele: Zielgröße xG, wo vorhanden
    (fünf große Ligen von Understat, CL von FotMob), sonst Tore. Startstärke aus dem Kaderwert relativ zum
    europäischen Mittel. Optional Formkomponente und Mischung mit dem Elo-Modell."""

    value_k: float = 0.25  # Angriff = k·z, Abwehr = −k·z mit z = log(Kaderwert) − Mittel
    ridge: float = 5.0
    xi: float = 0.003  # Halbwertszeit ~ 8 Monate
    w_xg: float = 1.0  # 0 = nur Tore (Kontrolle)
    form_weight: float = 0.0  # 0 = aus; sonst zweites Dixon-Coles mit kurzer Halbwertszeit
    form_xi: float = 0.02
    alpha: float = 1.0  # Anteil Dixon-Coles an den Wahrscheinlichkeiten, Rest Elo-Modell
    train_years: float = 3.0


def _value_priors(values: dict, teams, cutoff: pd.Timestamp, k: float) -> dict:
    logv = {t: math.log(v) for t in teams if (v := value_at(values, t, cutoff))}
    if not logv or k <= 0:
        return {}
    mean = sum(logv.values()) / len(logv)
    return {t: (k * (lv - mean), -k * (lv - mean)) for t, lv in logv.items()}


@dataclass
class XgModel:
    dc: "DixonColes"
    form: "DixonColes | None"
    cfg: XgConfig

    @classmethod
    def fit(cls, df: pd.DataFrame, values: dict, cutoff: pd.Timestamp, cfg: XgConfig) -> "XgModel":
        from fussballdb.model.dixon_coles import DixonColes

        hist = df[df["finished"] & (df["kickoff"] < cutoff)
                  & (df["kickoff"] >= cutoff - pd.Timedelta(days=365 * cfg.train_years))]
        train = pd.DataFrame({"home_id": hist["home_id"], "away_id": hist["away_id"], "kickoff": hist["kickoff"],
                              "hg": hist["home_goals"], "ag": hist["away_goals"], "hxg": hist["home_xg"],
                              "axg": hist["away_xg"], "finished": True})
        teams = set(df["home_id"]) | set(df["away_id"])
        dc = DixonColes(xi=cfg.xi, ridge=cfg.ridge, w_xg=cfg.w_xg, priors=_value_priors(values, teams, cutoff, cfg.value_k))
        dc.fit(train, now=cutoff)
        form = None
        if cfg.form_weight > 0:
            form = DixonColes(xi=cfg.form_xi, ridge=cfg.ridge, w_xg=cfg.w_xg, priors=dc.priors).fit(train, now=cutoff)
        return cls(dc, form, cfg)

    def with_cfg(self, cfg: XgConfig) -> "XgModel":
        """Gleiche angepasste Modelle, andere Mischung (Form-Gewicht, alpha) für den Test."""
        return XgModel(self.dc, self.form, cfg)

    def form_factors(self, home: int, away: int) -> tuple[float, float] | None:
        """Wirkung der Form auf die Torerwartung (Heim, Gast), z. B. (1,08, 0,95) = +8 % / −5 %."""
        if self.form is None or self.cfg.form_weight <= 0:
            return None
        lh, la = self.dc.rates(home, away)
        fh, fa = self.form.rates(home, away)
        return (fh / lh) ** self.cfg.form_weight, (fa / la) ** self.cfg.form_weight

    def matrix(self, home: int, away: int, neutral: bool) -> np.ndarray:
        def one(h: int, a: int) -> np.ndarray:
            adj = (1.0, 1.0)
            if self.form is not None and self.cfg.form_weight > 0:
                lh, la = self.dc.rates(h, a)
                fh, fa = self.form.rates(h, a)
                adj = ((fh / lh) ** self.cfg.form_weight, (fa / la) ** self.cfg.form_weight)
            return self.dc.score_matrix(h, a, adj)

        if not neutral:
            return one(home, away)
        return (one(home, away) + one(away, home).T) / 2  # Finale: Heimvorteil herausmitteln


def rounds(df: pd.DataFrame, competition: str = "CL") -> pd.DataFrame:
    """Spieltage/Runden mit erstem Anpfiff (= Stichtag der Prognose)."""
    cl = df[df["competition"] == competition]
    return (cl.groupby(["season", "round_no", "round_name"], as_index=False)["kickoff"].min()
            .rename(columns={"kickoff": "cutoff"}).sort_values("cutoff"))


def rps(p: tuple[float, float, float], outcome: int) -> float:
    """Ranked Probability Score für Heim/Remis/Gast (outcome 0/1/2)."""
    o = np.zeros(3)
    o[outcome] = 1
    cp, co = np.cumsum(p), np.cumsum(o)
    return float(((cp[:2] - co[:2]) ** 2).sum() / 2)


def _outcome(h: int, a: int) -> int:
    return 0 if h > a else 1 if h == a else 2


def backtest(config: EloConfig | None = None, competitions=("CL",), log=print) -> pd.DataFrame:
    """Jede gespielte CL-Runde mit dem Stand vor ihrem ersten Anpfiff vorhersagen. Vergleicht das Modell
    mit Elo + Kaderwert-Merkmal, Kaderwert allein und der Grundverteilung."""
    df, values = load_matches(), load_values()
    st = run_elo(df, values, config)
    feats = all_features(df, st, values)
    rows = []
    for comp in competitions:
        for r in rounds(df, comp).itertuples():
            ms = df[(df["competition"] == comp) & (df["season"] == r.season) & (df["round_no"] == r.round_no)
                    & df["finished"]]
            if ms.empty:
                continue
            variants = {"Modell": (True, USE_VALUE), "Elo + Kaderwert": (True, True), "nur Kaderwert": (False, True)}
            preds = {name: predict_round(feats, st, values, r.cutoff, ms, *flags) for name, flags in variants.items()}
            hist = df[df["finished"] & (df["kickoff"] < r.cutoff) & df["competition"].isin(EURO)]
            base = np.array([(hist["home_goals"] > hist["away_goals"]).mean(), (hist["home_goals"] == hist["away_goals"]).mean(),
                             (hist["home_goals"] < hist["away_goals"]).mean()]) if len(hist) > 50 else np.array([0.45, 0.24, 0.31])
            for i, m in enumerate(ms.itertuples()):
                o = _outcome(m.home_goals, m.away_goals)
                row = {"competition": comp, "season": m.season, "round": m.round_name, "match_id": m.id,
                       "home": m.home, "away": m.away, "goals": f"{int(m.home_goals)}:{int(m.away_goals)}",
                       "rps_Grundverteilung": rps(tuple(base), o)}
                for name, pr in preds.items():
                    p = pr[i]
                    row[f"rps_{name}"] = rps((p["p_home"], p["p_draw"], p["p_away"]), o)
                    row[f"ll_{name}"] = -math.log(max([p["p_home"], p["p_draw"], p["p_away"]][o], 1e-9))
                    if name == "Modell":
                        row["tip"] = f"{p['tip'][0]}:{p['tip'][1]}"
                        row["punkte"] = kicktipp_points(*p["tip"], m.home_goals, m.away_goals)
                        row["p"] = (round(p["p_home"], 3), round(p["p_draw"], 3), round(p["p_away"], 3))
                rows.append(row)
            log(f"{comp} {r.season}/{(r.season + 1) % 100:02d} {r.round_name}: {len(ms)} Spiele")
    return pd.DataFrame(rows)


# --- Begründung und Speichern ------------------------------------------------------------------------

def _pct(x: float) -> str:
    return f"{round(100 * x)} %"


def _de(x: float, digits: int) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def _mio(v: float | None) -> str:
    if not v:
        return "?"
    return f"{_de(v / 1e9, 2)} Mrd. €" if v >= 1e9 else f"{v / 1e6:.0f} Mio. €"


def explain(p: dict, home: str, away: str, neutral: bool) -> list[str]:
    fav, fav_p = (home, p["p_home"]) if p["p_home"] >= p["p_away"] else (away, p["p_away"])
    lines = [f"{fav} Favorit, {_pct(fav_p)} Siegchance: erwartet {_de(p['exp_home'], 1)} : {_de(p['exp_away'], 1)} Tore"]
    lines.append(f"Europa-Elo {p['elo_home']:.0f} : {p['elo_away']:.0f}")
    form = p.get("form")
    if form:
        parts = [f"{t} {'+' if f >= 1 else '−'}{round(abs(f - 1) * 100)} % Tore" for t, f in zip((home, away), form)
                 if abs(f - 1) >= 0.05]
        if parts:
            lines.append("Form der letzten Wochen (xG): " + ", ".join(parts))
    if p.get("value_home") and p.get("value_away"):
        ratio = p["value_home"] / p["value_away"]
        rel = f"{_de(ratio if ratio >= 1 else 1 / ratio, 1)}-fach"
        richer = home if ratio >= 1 else away
        lines.append(f"Kaderwert {_mio(p['value_home'])} : {_mio(p['value_away'])} ({richer} {rel})")
    if neutral:
        lines.append("Finale auf neutralem Platz, kein Heimvorteil")
    opts = p["tip_options"]
    others = " · ".join(f"{h}:{a} {_de(pts, 2)}" for (h, a), pts in opts[1:3])
    lines.append(f"{opts[0][0][0]}:{opts[0][0][1]} bringt im Schnitt {_de(opts[0][1], 2)} Punkte"
                 + (f" (zum Vergleich {others})" if others else ""))
    return lines


def _store(rows: list[dict]) -> int:
    if not rows:
        return 0
    from fussballdb.db.models import EuPrediction
    from fussballdb.db.session import session_scope
    from fussballdb.ingest.upsert import upsert

    with session_scope() as s:
        upsert(s, EuPrediction, rows, ["match_id", "basis"])
    return len(rows)


def _row(p: dict, m, basis: str, as_of: pd.Timestamp) -> dict:
    return {"match_id": int(m.id), "basis": basis, "as_of": as_of.to_pydatetime(), "model_version": MODEL_VERSION,
            "p_home": p["p_home"], "p_draw": p["p_draw"], "p_away": p["p_away"],
            "exp_home_goals": p["exp_home"], "exp_away_goals": p["exp_away"],
            "elo_home": p["elo_home"], "elo_away": p["elo_away"],
            "value_home": p["value_home"], "value_away": p["value_away"],
            "tip_home": p["tip"][0], "tip_away": p["tip"][1],
            "explanation": json.dumps(explain(p, m.home, m.away, bool(m.neutral)), ensure_ascii=False)}


ACTIVE_XG: XgConfig | None = XgConfig(alpha=0.7, form_weight=0.4)  # None = nur Elo


def backfill(competition: str = "CL", force: bool = False) -> int:
    """Rückblick-Prognosen für gespielte Runden (Stand vor dem ersten Anpfiff der Runde)."""
    df, values = load_matches(), load_values()
    st = run_elo(df, values)
    feats = all_features(df, st, values)
    with engine.connect() as conn:
        done = {r[0] for r in conn.execute(text("SELECT match_id FROM eu_prediction WHERE basis = 'rueckblick'"))}
    rows = []
    for r in rounds(df, competition).itertuples():
        ms = df[(df["competition"] == competition) & (df["season"] == r.season) & (df["round_no"] == r.round_no)
                & df["finished"]]
        if not force:
            ms = ms[~ms["id"].isin(done)]
        if ms.empty:
            continue
        xm = XgModel.fit(df, values, r.cutoff, ACTIVE_XG) if ACTIVE_XG else None
        for p, m in zip(predict_round(feats, st, values, r.cutoff, ms, use_value=USE_VALUE, xg_model=xm),
                        ms.itertuples()):
            rows.append(_row(p, m, "rueckblick", r.cutoff))
    return _store(rows)


def predict_upcoming(competition: str = "CL") -> int:
    """Live-Prognosen für alle offenen Spiele mit dem heutigen Stand (bis zum Anpfiff überschrieben)."""
    df, values = load_matches(), load_values()
    st = run_elo(df, values)
    now = pd.Timestamp(datetime.now(timezone.utc))
    ms = df[(df["competition"] == competition) & ~df["finished"] & (df["kickoff"] > now)]
    if ms.empty:
        return 0
    feats = all_features(df, st, values)
    xm = XgModel.fit(df, values, now, ACTIVE_XG) if ACTIVE_XG else None
    rows = [_row(p, m, "live", now)
            for p, m in zip(predict_round(feats, st, values, now, ms, use_value=USE_VALUE, xg_model=xm), ms.itertuples())]
    return _store(rows)


XG_VARIANTS: dict[str, XgConfig | None] = {
    "Elo (bisher)": None,
    "xG": XgConfig(),
    "xG + Form": XgConfig(form_weight=0.4),
    "xG/Elo 70/30": XgConfig(alpha=0.7),
    "xG/Elo 70/30 + Form": XgConfig(alpha=0.7, form_weight=0.4),
    "xG/Elo 50/50 + Form": XgConfig(alpha=0.5, form_weight=0.4),
    "Tore statt xG, 70/30 + Form": XgConfig(alpha=0.7, form_weight=0.4, w_xg=0.0),
    "xG k 0,15, 70/30 + Form": XgConfig(alpha=0.7, form_weight=0.4, value_k=0.15),
    "xG k 0,35, 70/30 + Form": XgConfig(alpha=0.7, form_weight=0.4, value_k=0.35),
}


def backtest_xg(variants: dict[str, XgConfig | None] | None = None, log=print) -> pd.DataFrame:
    """Rückblick-Test aller CL-Runden für das Elo-Modell und die xG-Varianten. Je Runde wird jedes
    xG-Modell (Kaderwert-Gewicht, xG/Tore) einmal mit Formkomponente angepasst; die Varianten
    unterscheiden sich danach nur in der Mischung. Liefert je Spiel und Variante RPS, Log-Loss und Punkte."""
    variants = variants or XG_VARIANTS
    df, values = load_matches(), load_values()
    st = run_elo(df, values)
    feats = all_features(df, st, values)
    rows = []
    for r in rounds(df, "CL").itertuples():
        ms = df[(df["competition"] == "CL") & (df["season"] == r.season) & (df["round_no"] == r.round_no) & df["finished"]]
        if ms.empty:
            continue
        fitted: dict = {}
        preds = {}
        for name, cfg in variants.items():
            xm = None
            if cfg is not None:
                key = (cfg.value_k, cfg.w_xg, cfg.ridge, cfg.xi)
                if key not in fitted:
                    fitted[key] = XgModel.fit(df, values, r.cutoff, XgConfig(value_k=cfg.value_k, w_xg=cfg.w_xg,
                                                                                ridge=cfg.ridge, xi=cfg.xi, form_weight=0.4))
                xm = fitted[key].with_cfg(cfg)
            preds[name] = predict_round(feats, st, values, r.cutoff, ms, use_value=USE_VALUE, xg_model=xm)
        for i, m in enumerate(ms.itertuples()):
            o = _outcome(m.home_goals, m.away_goals)
            row = {"season": m.season, "round": m.round_name, "match_id": m.id}
            for name, pr in preds.items():
                p = pr[i]
                row[f"rps|{name}"] = rps((p["p_home"], p["p_draw"], p["p_away"]), o)
                row[f"ll|{name}"] = -math.log(max([p["p_home"], p["p_draw"], p["p_away"]][o], 1e-9))
                row[f"pkt|{name}"] = kicktipp_points(*p["tip"], int(m.home_goals), int(m.away_goals))
            rows.append(row)
        log(f"{r.season}/{(r.season + 1) % 100:02d} {r.round_name}: {len(ms)} Spiele")
    return pd.DataFrame(rows)


def compare_xg(res: pd.DataFrame, base: str = "Elo (bisher)", tune=(2024,), seed: int = 0) -> pd.DataFrame:
    """Zusammenfassung von backtest_xg: RPS gesamt, im Einstell- (2024/25) und Testzeitraum, Bootstrap-Anteil
    der Ziehungen im Testzeitraum, in denen die Variante besser ist als `base`."""
    names = [c.split("|", 1)[1] for c in res.columns if c.startswith("rps|")]
    is_tune = res["season"].isin(tune).to_numpy()
    rng = np.random.default_rng(seed)
    test_idx = np.flatnonzero(~is_tune)
    boot = rng.choice(test_idx, (4000, len(test_idx)))
    base_rps = res[f"rps|{base}"].to_numpy()
    out = []
    for n in names:
        d = res[f"rps|{n}"].to_numpy() - base_rps
        out.append({"variante": n, "rps": res[f"rps|{n}"].mean(), "rps_einstellen": res.loc[is_tune, f"rps|{n}"].mean(),
                    "rps_test": res.loc[~is_tune, f"rps|{n}"].mean(), "logloss": res[f"ll|{n}"].mean(),
                    "punkte": res[f"pkt|{n}"].mean(),
                    "test_besser_pct": 100 * (d[boot].mean(1) < 0).mean() if n != base else np.nan})
    return pd.DataFrame(out).sort_values("rps_test")
