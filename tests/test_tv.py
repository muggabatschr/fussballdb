from fussballdb.ingest.tv import channels


def test_exact_channels_without_copies():
    de = ["Sky Top Event", "Sky Bundesliga", "Sky Bundesliga UHD", "Sky Bundesliga 1", "Sky Showcase", "WOW"]
    assert channels(de) == ["Sky Bundesliga 1", "WOW"]
    at = ["Sky Sport Bundesliga 3", "Sky Sport Bundesliga", "WOW"]
    assert channels(at) == ["Sky Sport Bundesliga 3", "WOW"]
    cl_at = ["Sky Sport Austria 1", "Sky Sport Austria 4", "Sky Go", "WOW"]
    assert channels(cl_at) == ["Sky Sport Austria 1", "Sky Sport Austria 4", "WOW"]
    assert channels(["DAZN Deutschland"]) == ["DAZN"]
    assert channels(["Prime Video (DE)"]) == ["Prime Video"]
    assert channels(["Noch zu bestätigen"]) == []



def test_align_sky_numbers():
    from fussballdb.ingest.tv import align_sky_numbers

    # LiveOnSat gilt für beide Länder und wird selbst nicht angezeigt
    tv = {"DE": ["Sky Bundesliga 2", "WOW"], "AT": ["Sky Sport Bundesliga 4", "WOW"], "LS": ["Sky Sport Bundesliga 4"]}
    assert align_sky_numbers(tv) == {"DE": ["Sky Bundesliga 4", "WOW"], "AT": ["Sky Sport Bundesliga 4", "WOW"]}
    # ohne LiveOnSat zählt die österreichische Nummer
    tv = {"DE": ["Sky Bundesliga 2", "WOW"], "AT": ["Sky Sport Bundesliga 4", "WOW"]}
    assert align_sky_numbers(tv)["DE"] == ["Sky Bundesliga 4", "WOW"]
    # ohne nummerierte Kanäle bleibt alles, wie es ist
    assert align_sky_numbers({"DE": ["DAZN"], "AT": ["DAZN"]}) == {"DE": ["DAZN"], "AT": ["DAZN"]}
    assert align_sky_numbers({"DE": ["Sky Bundesliga 1"]}) == {"DE": ["Sky Bundesliga 1"]}


def test_conference_marked_when_on_every_game_of_a_slot():
    from datetime import datetime, timezone

    from fussballdb.ingest.tv import channels, mark_conference

    k = datetime(2026, 10, 27, 17, tzinfo=timezone.utc)
    games = [{"competition": "DFB", "kickoff": k, "channels": ["Sky Sport 1", f"Sky Sport {n}", "WOW"]} for n in (2, 3, 4)]
    games.append({"competition": "DFB", "kickoff": k.replace(hour=19), "channels": ["Sky Sport 1", "WOW"]})
    out = mark_conference(games)
    assert out[0]["channels"][0] == "Sky Sport 1 (Konferenz)" and out[3]["channels"][0] == "Sky Sport 1"
    assert channels(out[0]["channels"]) == ["Sky Sport 1 (Konferenz)", "Sky Sport 2", "WOW"]


def test_conference_copied_to_germany():
    import json

    from fussballdb.ingest.tv import conference_to_de

    rows = [{"competition": "DFB", "match_id": 1, "country": "AT", "channels": json.dumps(["Sky Sport 1 (Konferenz)", "Sky Sport 4"])},
            {"competition": "DFB", "match_id": 1, "country": "DE", "channels": json.dumps(["Sky Sport 4", "RTL+"])},
            {"competition": "DFB", "match_id": 2, "country": "AT", "channels": json.dumps(["Sky Sport 1 (Konferenz)"])},
            {"competition": "DFB", "match_id": 2, "country": "DE", "channels": json.dumps(["ZDF"])}]
    out = conference_to_de(rows)
    assert json.loads(out[1]["channels"]) == ["Sky Sport 1 (Konferenz)", "Sky Sport 4", "RTL+"]
    assert json.loads(out[3]["channels"]) == ["ZDF"]  # ohne Sky in Deutschland keine Konferenz
