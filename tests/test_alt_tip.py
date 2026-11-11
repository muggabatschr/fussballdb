import math

import numpy as np

from fussballdb.features.stat_form import StatForm
from fussballdb.model.alt_tip import ALT_BETAS, explanation


def test_stat_factor_raises_own_and_lowers_opponent_goals():
    z = {"schuesse": 1.0, "aufs_tor": 1.0, "ecken": 1.0}
    out = StatForm.apply({"attack_mult": 1.0}, z, ALT_BETAS)
    assert math.isclose(out["attack_mult"], math.exp(0.045)) and math.isclose(out["concede_mult"], math.exp(-0.045))
    assert StatForm.apply({"x": 1}, None, ALT_BETAS) == {"x": 1}  # ohne Daten keine Änderung


def test_more_rest_counts_slightly_negative():
    out = StatForm.apply({}, None, ALT_BETAS, rest=1.0)
    assert out["attack_mult"] < 1


def test_explanation_names_teams_rest_and_tip():
    m = np.full((4, 4), 1 / 16)
    main = {"exp_home_goals": 1.5, "exp_away_goals": 1.0, "p_home": 0.45, "p_draw": 0.27, "p_away": 0.28}
    alt = {**main, "exp_home_goals": 1.6, "score_probs": m}
    info = {"z_home": {"schuesse": 1.0, "aufs_tor": 0.5, "ecken": float("nan")}, "z_away": None,
            "rest_home": 7, "rest_away": 6, "rest_z": 1 / 3,
            "scale": {"shots": 4.0, "shots_on_target": 2.0, "corners": 2.0}}
    lines = explanation(main, alt, info, "Freiburg", "Leipzig")
    assert any(line.startswith("Freiburg je Spiel") and "Schüsse +4,0" in line for line in lines)
    assert any("1 Tag mehr Pause" in line for line in lines)
    assert "bringt im Schnitt" in lines[-1]
