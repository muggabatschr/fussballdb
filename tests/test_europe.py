import math

import numpy as np
import pandas as pd

from fussballdb.ingest.europe import _norm
from fussballdb.model.europe import EloConfig, GoalModel, probs_from, rps, run_elo, value_at


def _match(i, day, home, away, hg, ag, comp="E0", neutral=False):
    return {"id": i, "competition": comp, "season": 2024, "round_no": 1, "round_name": "1. Spieltag",
            "kickoff": pd.Timestamp(day, tz="UTC"), "home_id": home, "away_id": away, "home_goals": hg,
            "away_goals": ag, "finished": True, "neutral": neutral, "home": str(home), "away": str(away),
            "home_country": comp, "away_country": comp}


def _values(entries):
    out = {}
    for team, day, v in entries:
        days, vals = out.setdefault(team, ([], []))
        days.append(pd.Timestamp(day, tz="UTC"))
        vals.append(v)
    return out


def test_start_elo_from_squad_value_and_update():
    values = _values([(1, "2024-07-01", 800e6), (2, "2024-07-01", 50e6)])
    df = pd.DataFrame([_match(1, "2024-08-10", 1, 2, 0, 1)])
    st = run_elo(df, values, EloConfig(season_pull=0))
    pre_home, pre_away = st.pre[1]
    # Start aus dem Kaderwert: 16-facher Wert = 4 Verdopplungen über dem Basiswert
    assert math.isclose(pre_away, 1500.0)
    assert math.isclose(pre_home, 1500.0 + 150 * math.log(16))
    # Überraschung: der Favorit verliert deutlich Elo, der Außenseiter gewinnt gleich viel
    assert st.rating[1] < pre_home and st.rating[2] > pre_away
    assert math.isclose(st.rating[1] - pre_home, -(st.rating[2] - pre_away))


def test_elo_history_is_point_in_time():
    values = _values([(1, "2024-07-01", 100e6), (2, "2024-07-01", 100e6)])
    df = pd.DataFrame([_match(1, "2024-08-10", 1, 2, 3, 0), _match(2, "2024-08-20", 2, 1, 0, 0)])
    st = run_elo(df, values)
    # vor dem ersten Spiel unbekannt, danach der Stand nach Spiel 1, nicht nach Spiel 2
    assert st.at(1, pd.Timestamp("2024-08-01", tz="UTC")) is None
    after_first = st.history[1][1][0]
    assert st.at(1, pd.Timestamp("2024-08-15", tz="UTC")) == after_first
    assert value_at(values, 1, pd.Timestamp("2024-06-30", tz="UTC")) is None


def test_goal_model_learns_strength_and_home_advantage():
    rng = np.random.default_rng(1)
    n = 3000
    elo_d = rng.normal(0, 0.4, n)
    lh, la = np.exp(0.25 + 0.2 + 0.9 * elo_d), np.exp(0.25 - 0.9 * elo_d)
    train = pd.DataFrame({"home_goals": rng.poisson(lh), "away_goals": rng.poisson(la), "elo_d": elo_d,
                          "val_d": np.zeros(n), "neutral": False, "competition": "E0"})
    model = GoalModel.fit(train, use_value=False)
    assert abs(model.params["b_elo"] - 0.9) < 0.1
    assert abs(model.params["home_league"] - 0.2) < 0.08
    strong = probs_from(model.matrix(0.5, 0.0, neutral=False, euro=False))
    neutral = probs_from(model.matrix(0.0, 0.0, neutral=True, euro=False))
    assert strong["p_home"] > 0.6
    assert abs(neutral["p_home"] - neutral["p_away"]) < 0.01  # Finale ohne Heimvorteil


def test_rps_and_name_normalisation():
    assert rps((1, 0, 0), 0) == 0
    assert math.isclose(rps((0, 0, 1), 0), 1.0)
    assert _norm("FC Bayern München") == "bayern munchen"
    assert _norm("Atlético Madrid") == "atletico madrid"
