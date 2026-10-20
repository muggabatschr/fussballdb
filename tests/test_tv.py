from fussballdb.ingest.tv import simplify


def test_channels_grouped_per_country():
    de = ["WOW", "Sky Bundesliga 5", "Sky Top Event", "DAZN Deutschland", "Prime Video (DE)"]
    assert simplify(de, "DE") == ["Sky", "DAZN", "Prime Video", "WOW"]
    at = ["Sky Go", "Sky Sport Austria 1", "WOW", "Sky Sport Bundesliga 2", "Noch zu bestätigen", "Canal+ First"]
    assert simplify(at, "AT") == ["Sky Austria", "Canal+", "WOW"]
