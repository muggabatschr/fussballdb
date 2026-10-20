import pandas as pd

from fussballdb.model import season_sim


def test_simulation_respects_probabilities(monkeypatch):
    played = pd.DataFrame([{"home": "A", "away": "B", "hg": 0, "ag": 1}, {"home": "C", "away": "D", "hg": 1, "ag": 1}])
    # A gewinnt die offenen Spiele fast sicher, B verliert sie fast sicher
    open_ = pd.DataFrame([
        {"home": "A", "away": "C", "p_home": 0.98, "p_draw": 0.01, "p_away": 0.01, "eh": 3.0, "ea": 0.3},
        {"home": "D", "away": "B", "p_home": 0.98, "p_draw": 0.01, "p_away": 0.01, "eh": 3.0, "ea": 0.3},
        {"home": "A", "away": "D", "p_home": 0.98, "p_draw": 0.01, "p_away": 0.01, "eh": 3.0, "ea": 0.3},
    ])
    monkeypatch.setattr(season_sim, "_load", lambda season: (played, open_))
    res = season_sim.simulate(2026, n=2000).set_index("name")
    assert res.loc["B", "platz"] == 1 and res.loc["A", "platz"] == 4  # heute: B vorn, A hinten
    assert res.loc["A", "prognose_platz"] == 1 and res.loc["A", "platz_diff"] == 3
    assert res.loc["A", "p_meister"] > 90
    assert abs(res["p_meister"].sum() - 100) < 0.5
