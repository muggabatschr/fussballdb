import numpy as np
import pandas as pd

from fussballdb.ingest.absences import normalize
from fussballdb.model.dixon_coles import DixonColes
from fussballdb.model.elo import EloOutcomeModel
from fussballdb.model.evaluate import scores


def _synthetic(n_rounds: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    strength = {1: 0.5, 2: 0.0, 3: -0.5, 4: 0.0}
    rows, mid = [], 0
    start = pd.Timestamp("2025-08-01", tz="UTC")
    for r in range(n_rounds):
        for h in strength:
            for a in strength:
                if h == a:
                    continue
                mid += 1
                lh = np.exp(0.3 + 0.25 + strength[h] - strength[a] * 0.5)
                la = np.exp(0.3 + strength[a] - strength[h] * 0.5)
                rows.append({"match_id": mid, "kickoff": start + pd.Timedelta(days=mid), "home_id": h, "away_id": a,
                             "hg": rng.poisson(lh), "ag": rng.poisson(la), "hxg": lh, "axg": la, "finished": True})
    return pd.DataFrame(rows)


def test_dixon_coles_probabilities_are_consistent():
    model = DixonColes(min_matches=1).fit(_synthetic())
    p = model.predict(1, 3)
    assert abs(p["p_home"] + p["p_draw"] + p["p_away"] - 1) < 1e-9
    assert p["p_home"] > p["p_away"]  # stärkeres Team zuhause
    assert model.home_adv > 0
    assert model.att[1] > model.att[3]


def test_adjustment_lowers_expected_goals():
    model = DixonColes(min_matches=1).fit(_synthetic())
    base = model.predict(2, 4)
    weakened = model.predict(2, 4, adj=(0.8, 1.0))
    assert weakened["exp_home_goals"] < base["exp_home_goals"]
    assert weakened["p_home"] < base["p_home"]


def test_elo_outcome_model_rows_sum_to_one():
    probs = EloOutcomeModel().predict([1600, 1500], [1500, 1600])
    assert np.allclose(probs.sum(axis=1), 1)
    assert probs[0, 2] > probs[1, 2]  # höhere Heim-Elo -> höhere Heimsiegchance


def test_scores_perfect_forecast():
    s = scores(np.array([[1.0, 0, 0], [0, 0, 1.0]]), np.array([0, 2]))
    assert s["rps"] == 0 and s["brier"] == 0 and s["accuracy"] == 1


def test_normalize_player_names():
    assert normalize("Berkay Yılmaz") == "berkay yilmaz"
    assert normalize("Emil Højlund") == "emil hojlund"
    assert normalize("Samuele Inácio") == normalize("Samuele Inacio")
    assert normalize("Ransford Königsdörffer") == normalize("Ransford Koenigsdoerffer")
    assert normalize("Alessio Castro-Montes") == normalize("Alessio Castro Montes")


def test_player_profile_uses_most_recent_matches():
    """Regression: das Profil muss die letzten Spiele nehmen, nicht beliebige (unsortierte) Zeilen."""
    import pandas as pd

    from fussballdb.features.availability import AvailabilityModel

    av = AvailabilityModel.__new__(AvailabilityModel)
    av.window, av.regular_share, av.beta, av.gamma, av.floor, av.cap = 2, 0.5, 0.8, 0.06, 0.75, 1.2
    rows = []
    for mid, day, player in [(3, "2025-03-01", "Neu"), (1, "2024-01-01", "Alt"), (2, "2025-02-01", "Neu")]:
        rows.append({"match_id": mid, "player_id": 1 if player == "Alt" else 2, "name": player, "team_id": 9,
                     "position": "FW", "started": True, "minutes": 90, "xg": 0.5, "xa": 0.1, "red_cards": 0,
                     "kickoff": pd.Timestamp(day, tz="UTC")})
    av.apps = pd.DataFrame(rows)
    av.apps["xgxa"] = av.apps["xg"] + av.apps["xa"]
    prof = av.player_profile(9, pd.Timestamp("2026-01-01", tz="UTC"))
    assert set(prof["name"]) == {"Neu"}


def test_kicktipp_points():
    from fussballdb.model.ensemble import kicktipp_points

    rule = (2, 3, 4, 3)  # Tipprunde: richtiges Remis = 3 Punkte
    assert kicktipp_points(2, 1, 2, 1, rule) == 4
    assert kicktipp_points(2, 1, 3, 2, rule) == 3
    assert kicktipp_points(2, 1, 3, 0, rule) == 2
    assert kicktipp_points(1, 1, 2, 2, rule) == 3
    assert kicktipp_points(1, 0, 0, 1, rule) == 0
    assert kicktipp_points(1, 1, 2, 2, (2, 3, 4, 2)) == 2  # Kicktipp-Standard


def test_expected_points_tip_picks_draw_when_even():
    from fussballdb.model.ensemble import tip, tip_expected_points

    model = DixonColes(min_matches=1).fit(_synthetic())
    m = model.score_matrix(2, 4)
    even = {"p_home": 0.36, "p_draw": 0.30, "p_away": 0.34}
    assert tip(m, even)[0] > tip(m, even)[1]  # alter Tipp: immer die wahrscheinlichste Tendenz
    h, a = tip_expected_points(m, even)
    assert 0 <= h <= 5 and 0 <= a <= 5


def test_monthly_stichtage_uses_available_dates():
    from datetime import date

    from fussballdb.ingest.squad_values import monthly_stichtage

    available = [date(2014, 7, 10), date(2014, 10, 23), date(2014, 11, 1), date(2014, 11, 15)]
    assert monthly_stichtage(date(2014, 7, 1), date(2014, 11, 30), available) == [
        date(2014, 7, 10), date(2014, 10, 23), date(2014, 11, 1)]
