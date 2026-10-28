"""Tabelle der Champions-League-Ligaphase (8 Spieltage, 36 Teams) mit Modell-Platz und Hochrechnung.

- Modell-Punkte: in den gespielten Spielen erwartete Punkte laut Prognose vor dem Spiel (3 × Siegchance +
  Remischance); Modell-Platz = Platz nach diesen Punkten, platz_diff > 0 = steht besser als erwartet.
- Hochrechnung: alle offenen Spiele der Ligaphase 10.000-mal mit den Wahrscheinlichkeiten der
  Live-Prognosen durchgespielt. Platz 1–8 geht direkt ins Achtelfinale, 9–24 in die Play-offs, 25–36
  scheidet aus. Bei Punktgleichheit entscheidet die erwartete Tordifferenz, danach die Tore, dann der Zufall.
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

LEAGUE_PHASE_ROUNDS = 8
N_SIMS = 10_000

# Tabellen je Wettbewerb: berücksichtigte Runden und Zonen (Schlüssel, Beschriftung, Platz von, bis)
WINS_FIRST = ("BRA",)  # Tabellen, in denen bei Punktgleichheit zuerst die Siege zählen
ZONES = {
    "CL": {"rounds": LEAGUE_PHASE_ROUNDS, "zones": [("p_achtelfinale", "Achtelfinale", 1, 8),
                                                   ("p_playoffs", "Play-offs", 9, 24), ("p_aus", "Aus", 25, 36)]},
    "D2": {"rounds": 34, "zones": [("p_aufstieg", "Aufstieg", 1, 2), ("p_relegation_oben", "Relegation", 3, 3),
                                   ("p_relegation_unten", "Rel. unten", 16, 16), ("p_abstieg", "Abstieg", 17, 18)]},
    # Série A 2026 (CBF-Regeln laut brasilianischer Presse): 1–4 Libertadores-Gruppenphase, 5 Libertadores-
    # Qualifikation, 6–11 Copa Sudamericana, 17–20 Abstieg in die Série B
    "BRA": {"rounds": 38, "zones": [("p_libertadores", "Libertadores", 1, 4), ("p_libertadores_quali", "Lib.-Quali", 5, 5),
                                    ("p_sudamericana", "Sudamericana", 6, 11), ("p_abstieg", "Abstieg", 17, 20)]},
}

# Prognose je Spiel wie in der Rundenansicht: Live-Prognose von vor dem Anpfiff, sonst Rückblick
_PRED = """
    LEFT JOIN LATERAL (
        SELECT * FROM eu_prediction x WHERE x.match_id = m.id
        ORDER BY (x.basis = 'live' AND x.as_of <= m.kickoff) DESC, (x.basis = 'rueckblick') DESC LIMIT 1
    ) p ON true"""


def _load(season: int, competition: str = "CL", max_round: int = LEAGUE_PHASE_ROUNDS) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(f"""
            SELECT ht.name AS home, at.name AS away, m.home_goals AS hg, m.away_goals AS ag, m.finished,
                   p.p_home, p.p_draw, p.p_away, p.exp_home_goals AS eh, p.exp_away_goals AS ea
            FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
            {_PRED}
            WHERE m.competition = :c AND m.season = :y AND m.round_no <= :r"""),
            conn, params={"y": season, "r": max_round, "c": competition})


def _rank(points, goal_diff, goals) -> np.ndarray:
    order = np.lexsort((-goals, -goal_diff, -points))
    rank = np.empty(len(points), int)
    rank[order] = np.arange(1, len(points) + 1)
    return rank


def table(season: int, competition: str = "CL", n: int = N_SIMS, seed: int = 0) -> list[dict]:
    """Tabelle (CL-Ligaphase oder 2. Bundesliga), sortiert nach heutigem Platz. Felder der Hochrechnung nur,
    solange Spiele offen sind; die Zonen-Chancen stehen in ZONES."""
    cfg = ZONES[competition]
    df = _load(season, competition, cfg["rounds"])
    if df.empty:
        return []
    teams = sorted(set(df["home"]) | set(df["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    k = len(teams)
    home, away = df["home"].map(idx).to_numpy(), df["away"].map(idx).to_numpy()
    done = df["finished"].to_numpy(bool)

    sp, points, gd, goals, conceded, exp_pts, wins = (np.zeros(k) for _ in range(7))
    for r, h, a in zip(df[done].itertuples(), home[done], away[done]):
        hg, ag = int(r.hg), int(r.ag)
        sp[[h, a]] += 1
        points[h] += 3 if hg > ag else 1 if hg == ag else 0
        points[a] += 3 if ag > hg else 1 if hg == ag else 0
        wins[h] += hg > ag
        wins[a] += ag > hg
        gd[h] += hg - ag
        gd[a] += ag - hg
        goals[h] += hg
        goals[a] += ag
        conceded[h] += ag
        conceded[a] += hg
        if not pd.isna(r.p_home):
            exp_pts[h] += 3 * r.p_home + r.p_draw
            exp_pts[a] += 3 * r.p_away + r.p_draw
    wins_first = competition in WINS_FIRST
    # Brasilien: bei Punktgleichheit zuerst die Zahl der Siege, dann Tordifferenz und Tore
    rank_today = _rank(points, wins * 1e3 + gd, goals) if wins_first else _rank(points, gd, goals)
    has_model = df.loc[done, "p_home"].notna().any()
    model_rank = _rank(exp_pts, np.zeros(k), np.zeros(k)) if has_model else None

    rows = []
    for t, i in idx.items():
        row = {"name": t, "sp": int(sp[i]), "pkt": int(points[i]), "tore": int(goals[i]),
               "gegentore": int(conceded[i]), "platz": int(rank_today[i])}
        if has_model:
            row |= {"modell_pkt": round(float(exp_pts[i]), 1), "modell_platz": int(model_rank[i]),
                    "platz_diff": int(model_rank[i] - rank_today[i])}
        rows.append(row)

    open_ = df[~done]
    if not open_.empty:
        probs = open_[["p_home", "p_draw", "p_away"]].fillna(1 / 3).to_numpy()
        probs = probs / probs.sum(axis=1, keepdims=True)
        oh, oa = home[~done], away[~done]
        eh, ea = open_["eh"].fillna(1.4).to_numpy(), open_["ea"].fillna(1.1).to_numpy()
        exp_gd, exp_goals = gd.copy(), goals.copy()
        np.add.at(exp_gd, oh, eh - ea)
        np.add.at(exp_gd, oa, ea - eh)
        np.add.at(exp_goals, oh, eh)
        np.add.at(exp_goals, oa, ea)
        rng = np.random.default_rng(seed)
        u = rng.random((n, len(open_)))
        home_win = u < probs[:, 0]
        draw = (~home_win) & (u < probs[:, 0] + probs[:, 1])
        away_win = ~(home_win | draw)
        sim = np.tile(points, (n, 1))
        for col, (h, a) in enumerate(zip(oh, oa)):
            sim[:, h] += 3 * home_win[:, col] + draw[:, col]
            sim[:, a] += 3 * away_win[:, col] + draw[:, col]
        tiebreak = exp_gd / 1e3 + exp_goals / 1e6 + rng.random((n, k)) / 1e9
        if wins_first:  # Siege vor Tordifferenz (höchstens 38 Siege, also unter einem Punkt)
            sim_wins = np.tile(wins, (n, 1))
            for col, (h, a) in enumerate(zip(oh, oa)):
                sim_wins[:, h] += home_win[:, col]
                sim_wins[:, a] += away_win[:, col]
            tiebreak = sim_wins / 1e2 + exp_gd / 1e5 + exp_goals / 1e8 + rng.random((n, k)) / 1e11
        order = np.argsort(-(sim + tiebreak), axis=1)
        ranks = np.empty_like(order)
        ranks[np.arange(n)[:, None], order] = np.arange(1, k + 1)
        mean_rank = ranks.mean(axis=0)
        proj = np.empty(k, int)
        proj[np.lexsort((-sim.mean(axis=0), mean_rank))] = np.arange(1, k + 1)
        for row in rows:
            i = idx[row["name"]]
            row |= {"prognose_platz": int(proj[i]), "erw_punkte": round(float(sim[:, i].mean()), 1)}
            for key, _, lo, hi in cfg["zones"]:
                row[key] = round(100 * float(((ranks[:, i] >= lo) & (ranks[:, i] <= hi)).mean()), 1)
    return sorted(rows, key=lambda r: r["platz"])
