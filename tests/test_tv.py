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
