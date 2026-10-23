from pathlib import Path

import numpy as np

from fussballdb.ingest.kicktipp import parse_rules, slug_from_url
from fussballdb.model.tips import apply_rule, tip_options

RULES_PAGE = """<h2>Tippmodus</h2>Es wird das <b>genaue Ergebnis</b> getippt.
<h2>Tippabgaberegel: 15 Minuten Vorlaufzeit</h2>Die Tippzeit endet 15 Minuten vor dem Termin
<h2>Punkteregel: 1 - 3 Punkte</h2><table><tr><th></th><th>Tendenz</th><th>Tordifferenz</th><th>Ergebnis</th></tr>
<tr><td>Sieg</td><td>1</td><td>2</td><td>3</td></tr><tr><td>Unentschieden</td><td>2</td><td>-</td><td>3</td></tr></table>
<h2>Punkteregel: 5 Punkte</h2>Punkte pro richtiger Antwort: 5"""


def test_parse_kicktipp_rules():
    assert slug_from_url("https://www.kicktipp.de/waschndalos/") == "waschndalos"
    assert parse_rules(RULES_PAGE) == {"win_tendency": 1, "win_diff": 2, "exact": 3, "draw_tendency": 2,
                                       "lead_minutes": 15, "bonus_points": 5}


def _probs(cells: dict) -> list:
    m = np.full((10, 10), 1e-6)
    for (h, a), v in cells.items():
        m[h, a] = v
    return (m / m.sum()).tolist()


def test_rule_changes_tip_and_points():
    # Remis 1:1 zu 30 %, Remis insgesamt 35 %, Heimsiege 25 %, Auswärtssiege 40 % (verteilt)
    probs = _probs({(1, 1): 0.30, (0, 0): 0.05, (2, 1): 0.13, (1, 0): 0.12, (0, 1): 0.14, (1, 2): 0.13, (0, 2): 0.13})
    # Remis zählt 3 Punkte: 1:1 bringt 0,35·3 + 0,30·1 = 1,35, mehr als jeder Sieg-Tipp
    assert tip_options(probs, (2, 3, 4, 3), 1)[0][0] == (1, 1)
    # Remis-Tendenz zählt nichts, exakt 2: Auswärtssieg (40 %) gewinnt
    assert tip_options(probs, (2, 3, 2, 0), 1)[0][0][0] < tip_options(probs, (2, 3, 2, 0), 1)[0][0][1]
    game = {"tip_home": 2, "tip_away": 1, "finished": True, "home_goals": 1, "away_goals": 1, "points": 0,
            "explanation": ["2:1 bringt im Schnitt 1,00 Punkte", "anderes"], "score_probs": probs}
    out = apply_rule(game, (1, 2, 5, 3))
    assert (out["tip_home"], out["tip_away"]) == (1, 1) and out["points"] == 5  # exakt getroffen
    assert out["explanation"][0].startswith("1:1 bringt im Schnitt") and out["explanation"][1] == "anderes"
    assert "score_probs" not in out


def test_default_rule_keeps_stored_tip():
    from fussballdb.config import TIPP_PUNKTE

    game = {"tip_home": 2, "tip_away": 1, "points": 3, "explanation": [], "score_probs": _probs({(1, 1): 0.9})}
    assert apply_rule(game, TIPP_PUNKTE)["tip_home"] == 2  # gespeicherter Tipp bleibt


def test_bonus_question_kinds():
    from fussballdb.model.bonus import KINDS, _deadline

    def kind(text):
        return next((k for pattern, k in KINDS if pattern.search(text.lower())), None)

    assert kind("Wer wird Herbstmeister?")[2] == 17  # nicht Meister
    assert kind("Wer wird Deutscher Meister?")[:3] == ("p_meister", 3, None)
    assert kind("Welche Mannschaften belegen die Plätze 16-18?")[0] == "p_16_18"
    assert kind("Wo findet der erste Trainerwechsel statt?")[2] == 8
    from fussballdb.model.bonus import SCORER

    assert SCORER.search("welche mannschaft stellt den spieler mit den meisten toren?")
    assert _deadline("28.08.26 20:30").isoformat() == "2026-08-28T20:30:00+02:00"
