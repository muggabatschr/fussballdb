from fussballdb.ingest.matchpage import parse

PAGE = {
    "general": {"teamColors": {"lightMode": {"home": "#083890", "away": "#B8121C"},
                               "darkMode": {"home": "#0942ad", "away": "#B8121C"},
                               "fontLightMode": {"home": "#fff", "away": "#fff"},
                               "fontDarkMode": {"home": "#fff", "away": "#fff"}}},
    "content": {
        "lineup": {
            "lineupType": "standard",
            "homeTeam": {
                "name": "Schalke 04", "formation": "3-4-2-1", "rating": 6.6, "coach": {"name": "Miron Muslić"},
                "starters": [
                    {"name": "Loris Karius", "lastName": "Karius", "shirtNumber": "1", "isCaptain": False,
                     "horizontalLayout": {"x": 0.1, "y": 0.5}, "verticalLayout": {"x": 0.5, "y": 0.1},
                     "performance": {"rating": 8.7, "playerOfTheMatch": True, "events": [{"type": "yellowCard"}]}},
                    {"name": "Kenan Karaman", "lastName": "Karaman", "shirtNumber": "19", "isCaptain": True,
                     "horizontalLayout": {"x": 0.8, "y": 0.3}, "verticalLayout": {"x": 0.7, "y": 0.8},
                     "performance": {"rating": 6.5, "events": [{"type": "goal"}, {"type": "goal"}, {"type": "assist"}],
                                     "substitutionEvents": [{"time": 71, "type": "subOut"}]}},
                ],
                "subs": [{"name": "Junior Dina Ebimbe", "lastName": "Ebimbe", "shirtNumber": "29",
                          "performance": {"rating": 6.3, "substitutionEvents": [{"time": 71, "type": "subIn"}]}}],
            },
            "awayTeam": {"name": "Mainz 05", "formation": "3-5-2", "starters": [{"name": "Robin Zentner"}], "subs": []},
        },
        "momentum": {"main": {"data": [{"minute": 1, "value": -27}, {"minute": 2, "value": 40}]}},
        "matchFacts": {"events": {"events": [
            {"type": "Goal", "time": 24, "isHome": False, "nameStr": "Phillip Tietz", "newScore": [0, 1]},
            {"type": "Card", "card": "YellowRed", "time": 45, "overloadTime": 3, "isHome": True, "nameStr": "X"},
            {"type": "Card", "card": "Yellow", "time": 50, "isHome": True, "nameStr": "Y"},
            {"type": "Substitution", "time": 60, "isHome": True},
        ]}},
    },
}


def test_parse_lineup_momentum_events():
    p = parse(PAGE)
    home = p["lineup"]["home"]
    assert (home["formation"], home["trainer"], p["lineup"]["away"]["formation"]) == ("3-4-2-1", "Miron Muslić", "3-5-2")
    karius, karaman = home["startelf"]
    assert karius["spieler_des_spiels"] and karius["gelb"] and (karius["x"], karius["vy"]) == (0.1, 0.1)
    assert karaman["kapitaen"] and (karaman["tore"], karaman["vorlagen"], karaman["raus"]) == (2, 1, 71)
    assert home["bank"][0]["rein"] == 71
    assert p["momentum"] == [[1, -27], [2, 40]]
    # Tore und Platzverweise, keine Gelben Karten oder Wechsel
    assert [(e["art"], e["minute"], e["nachspiel"]) for e in p["events"]] == [("tor", 24, None), ("gelbrot", 45, 3)]
    assert p["colors"]["hell"] == {"home": "#083890", "away": "#B8121C"}


def test_pick_colors_secondary_when_clashing():
    from fussballdb.ingest.matchpage import SURFACE, _pick

    # beide weiß im Dunkelmodus: das Team mit der besser sichtbaren Zweitfarbe wechselt
    h, a = _pick(["#ffffff", "#d30029"], ["#ffffff", "#417e37"], SURFACE["dunkel"])
    assert h != a and {h, a} & {"#ffffff"}
    # passen schon: nichts ändern
    assert _pick(["#083890"], ["#b8121c"], SURFACE["hell"]) == ("#083890", "#b8121c")


def test_start_chance_combines_sources():
    from fussballdb.features.kickbase_projection import start_chance

    assert start_chance("alternative", "nicht_elf?", 0.8, 0.1) == (0.15, 0.45)  # beide sehen ihn nicht in der Elf
    assert start_chance("start", "elf?", 0.8, 0.1) == (0.92, 0.05)
    assert start_chance("alternative", "elf", 0.2, 0.1) == (0.98, 0.0)  # offizielle Aufstellung gilt allein
    assert start_chance("start", "fehlt", 0.9, 0.1) == (0.0, 0.0)
    assert start_chance(None, None, 0.7, 0.2) == (0.7, 0.2)
