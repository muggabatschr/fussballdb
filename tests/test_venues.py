from datetime import datetime, timezone

from fussballdb.ingest.venues import route


def test_route_arrival_local_time():
    # Anpfiff 20:30 in Stuttgart (MESZ) -> Ankunft 19:30 Ortszeit, kodiert als 19:30 "UTC"
    r = route(48.79228, 9.23202, datetime(2026, 10, 23, 18, 30, tzinfo=timezone.utc), "Germany", "Stuttgart Hbf")
    assert r["ankunft"] == "2026-10-23T19:30+02:00"
    assert "!8j1792783800!3e3" in r["url"] and "/dir/Stuttgart%20Hbf/48.79228,9.23202/" in r["url"]
    assert "{start}" in r["url_vorlage"] and "travelmode=transit" in r["url_ohne_zeit"]
    # Auswärtsspiel in England: 21:00 deutscher Zeit = 20:00 Ortszeit, Ankunft 19:00
    r = route(53.46, -2.29, datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc), "England")
    assert r["ankunft"] == "2026-11-03T19:00+00:00" and "/dir//53.46000" in r["url"]
