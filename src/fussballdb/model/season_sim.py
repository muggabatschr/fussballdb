"""Hochrechnung der Abschlusstabelle: die offenen Spiele der Saison mit den Wahrscheinlichkeiten des Modells
(gespeicherte Live-Prognosen) vielfach durchspielen.

Je Simulation wird für jedes offene Spiel Heimsieg, Remis oder Auswärtssieg nach den Modell-Wahrscheinlich-
keiten gezogen. Bei Punktgleichheit entscheidet die erwartete Tordifferenz (heutige Tordifferenz plus die
erwarteten Tore der offenen Spiele), danach der Zufall. Ergebnis je Team: erwartete Punkte, erwarteter
Endplatz und Wahrscheinlichkeiten für Meisterschaft, Champions League (Platz 1–4) und Abstieg (17–18).
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine
from fussballdb.model.ensemble import MODEL_VERSION

N_SIMS = 10_000


def _load(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    with engine.connect() as conn:
        played = pd.read_sql(text("""
            SELECT ht.name AS home, at.name AS away, m.home_goals AS hg, m.away_goals AS ag
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            WHERE s.start_year = :y AND m.finished"""), conn, params={"y": season})
        open_ = pd.read_sql(text("""
            SELECT ht.name AS home, at.name AS away, p.p_home, p.p_draw, p.p_away,
                   p.exp_home_goals AS eh, p.exp_away_goals AS ea
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            LEFT JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
            WHERE s.start_year = :y AND NOT m.finished"""), conn, params={"y": season, "v": MODEL_VERSION})
    return played, open_


def simulate(season: int, n: int = N_SIMS, seed: int = 0) -> pd.DataFrame:
    """Je Team: Punkte und Platz heute, erwartete Punkte, erwarteter Endplatz (prognose_platz),
    Differenz (positiv = besser als heute) und Wahrscheinlichkeiten in Prozent. Leer, wenn nichts mehr offen ist."""
    played, open_ = _load(season)
    if open_.empty or played.empty:
        return pd.DataFrame()
    teams = sorted(set(played["home"]) | set(played["away"]) | set(open_["home"]) | set(open_["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    k = len(teams)

    points = np.zeros(k)
    goal_diff = np.zeros(k)
    goals = np.zeros(k)
    for r in played.itertuples():
        h, a = idx[r.home], idx[r.away]
        points[h] += 3 if r.hg > r.ag else 1 if r.hg == r.ag else 0
        points[a] += 3 if r.ag > r.hg else 1 if r.hg == r.ag else 0
        goal_diff[h] += r.hg - r.ag
        goal_diff[a] += r.ag - r.hg
        goals[h] += r.hg
        goals[a] += r.ag
    # heutiger Platz: Punkte, Tordifferenz, Tore
    today = np.lexsort((-goals, -goal_diff, -points))
    rank_today = np.empty(k, int)
    rank_today[today] = np.arange(1, k + 1)

    # offene Spiele ohne Prognose (sollte nicht vorkommen) als ausgeglichen annehmen
    probs = open_[["p_home", "p_draw", "p_away"]].fillna(1 / 3).to_numpy()
    probs = probs / probs.sum(axis=1, keepdims=True)
    home = open_["home"].map(idx).to_numpy()
    away = open_["away"].map(idx).to_numpy()
    exp_gd = goal_diff.copy()
    eh, ea = open_["eh"].fillna(1.4).to_numpy(), open_["ea"].fillna(1.1).to_numpy()
    np.add.at(exp_gd, home, eh - ea)
    np.add.at(exp_gd, away, ea - eh)

    rng = np.random.default_rng(seed)
    u = rng.random((n, len(open_)))
    home_win = u < probs[:, 0]
    draw = (~home_win) & (u < probs[:, 0] + probs[:, 1])
    away_win = ~(home_win | draw)
    sim_points = np.tile(points, (n, 1))
    for col, (h, a) in enumerate(zip(home, away)):
        sim_points[:, h] += 3 * home_win[:, col] + draw[:, col]
        sim_points[:, a] += 3 * away_win[:, col] + draw[:, col]
    # Rang je Simulation: Punkte, dann erwartete Tordifferenz, dann Zufall
    tiebreak = exp_gd / 1000 + rng.random((n, k)) / 1e6
    order = np.argsort(-(sim_points + tiebreak), axis=1)
    ranks = np.empty_like(order)
    ranks[np.arange(n)[:, None], order] = np.arange(1, k + 1)

    mean_rank = ranks.mean(axis=0)
    # Prognose-Platz: Teams nach mittlerem Endplatz geordnet (bei Gleichstand nach erwarteten Punkten)
    proj_order = np.lexsort((-sim_points.mean(axis=0), mean_rank))
    proj = np.empty(k, int)
    proj[proj_order] = np.arange(1, k + 1)
    return pd.DataFrame({
        "name": teams,
        "pkt": points.astype(int),
        "platz": rank_today,
        "erw_punkte": sim_points.mean(axis=0).round(1),
        "erw_platz": mean_rank.round(1),
        "prognose_platz": proj,
        "platz_diff": rank_today - proj,
        "p_meister": (100 * (ranks == 1).mean(axis=0)).round(1),
        "p_top4": (100 * (ranks <= 4).mean(axis=0)).round(1),
        "p_abstieg": (100 * (ranks >= k - 1).mean(axis=0)).round(1),
    }).sort_values("platz")
