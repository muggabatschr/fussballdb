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
