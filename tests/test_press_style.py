import random
from types import SimpleNamespace

from fussballdb import press_style, reports
from fussballdb.press_style import Style, _diff, _verbs

NAMES = {1: "SV 07 Elversberg", 2: "1. FSV Mainz 05", 3: "FC Augsburg", 4: "SC Freiburg"}


def row(title, team, h, a, hg, ag):
    return SimpleNamespace(title=title, source="x", team_id=team, h=h, a=a, hg=hg, ag=ag)


def test_verbs_learned_with_outcome_and_margin():
    rows = [row("Elversberg überrollt Mainz und feiert deutlichen Heimsieg", 1, 1, 2, 4, 1),
            row("Ex-Münchner glänzt: Elversberg überrollt Mainz", 2, 1, 2, 4, 1),
            row("Nach Führung: FCA unterliegt Freiburg 1:2", 3, 3, 4, 1, 2),
            row("Augsburg unterliegt dem SC Freiburg", 4, 3, 4, 1, 2),
            row("Freiburg macht gegen Augsburg alles klar", 4, 3, 4, 1, 2),  # unvollständiges Verb
            row("Liveticker: Augsburg unterliegt Freiburg 1:2", 4, 3, 4, 1, 2)]  # Ticker zählt nicht
    v = _verbs(rows, NAMES)
    assert v["überrollt"]["ausgang"] == "S" and v["überrollt"]["aktiv"] and v["überrollt"]["ab_abstand"] == 3
    assert v["unterliegt"]["ausgang"] == "N" and v["unterliegt"]["n"] == 2 and v["unterliegt"]["mit_ergebnis"] == 0.5
    assert "macht gegen" not in v and "macht" not in v


def test_away_preposition_only_for_away_team():
    rows = [row("FC Bayern siegt in Freiburg", 1, 2, 1, 1, 3)]
    v = _verbs(rows, {1: "FC Bayern München", 2: "SC Freiburg"})
    assert v["siegt in"]["ausgang"] == "S"
    rows = [row("Freiburg siegt in Bayern", 1, 2, 1, 3, 1)]  # Heimteam mit "in": unsinnig, nicht gezählt
    assert "siegt in" not in _verbs(rows, {1: "FC Bayern München", 2: "SC Freiburg"})


def test_diff_lists_new_and_dropped():
    old = {"verben": {"schlägt": {"aktiv": True}}, "woerter": {"Krimi": {"aktiv": True}}, "spitznamen": {}}
    new = {"verben": {"schlägt": {"aktiv": True}, "düpiert": {"aktiv": True}}, "woerter": {"Krimi": {"aktiv": False}},
           "spitznamen": {"Bayer 04 Leverkusen": [{"name": "die Werkself", "aktiv": True}]}}
    assert _diff(old, new) == ["Verb neu: düpiert", "Wort weg: Krimi", "Spitzname neu: die Werkself"]
    assert _diff(new, new) == []


PROFILE = {"verben": {"überrollt": {"verb": "überrollt", "praep": None, "ausgang": "S", "aktiv": True, "ab_abstand": 3, "mit_ergebnis": 0},
                      "unterliegt": {"verb": "unterliegt", "praep": None, "ausgang": "N", "aktiv": True, "ab_abstand": 1, "mit_ergebnis": 1},
                      "siegt in": {"verb": "siegt", "praep": "in", "ausgang": "S", "aktiv": True, "ab_abstand": 1, "mit_ergebnis": 0}},
           "woerter": {}, "spitznamen": {"Bayer 04 Leverkusen": [{"name": "die Werkself", "dativ": "der Werkself", "n": 9, "aktiv": True}]}}


def match(hg, ag):
    return {"home_goals": hg, "away_goals": ag, "home_short": "Mainz", "away_short": "Elversberg", "home": "1. FSV Mainz 05",
            "away": "SV 07 Elversberg", "city": "Mainz", "style": Style(PROFILE)}


def test_press_headlines_respect_margin_and_venue():
    narrow = reports._press_headlines(match(1, 2), random.Random(1))
    assert "Elversberg siegt in Mainz" in narrow and "Mainz unterliegt Elversberg 1:2" in narrow
    assert not any("überrollt" in h for h in narrow)  # nur bei hohen Siegen gesehen
    assert "Elversberg überrollt Mainz" in reports._press_headlines(match(0, 4), random.Random(1))
    home_win = reports._press_headlines(match(2, 1), random.Random(1))
    assert not any("siegt in" in h for h in home_win)  # "in" nur auswärts


def test_nickname_only_when_used_by_press():
    m = {"home": "Bayer 04 Leverkusen", "home_short": "Leverkusen", "away": "SC Freiburg", "away_short": "Freiburg",
         "style": Style(PROFILE)}
    seen = {reports._nick(m, "home", random.Random(i), dative=True) for i in range(20)}
    assert seen == {"der Werkself", "Leverkusen"}
    assert {reports._nick(m, "away", random.Random(i)) for i in range(20)} == {"Freiburg"}


def test_empty_profile_keeps_old_behaviour():
    s = Style({})
    assert s.verbs == {"S": [], "N": []} and not s.has("Krimi") and s.nick("Bayer 04 Leverkusen") is None
    assert press_style.SCORE_FRONT_MIN > 0
