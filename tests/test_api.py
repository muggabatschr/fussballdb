"""Läuft gegen die echte Datenbank (docker compose up)."""

from fastapi.testclient import TestClient

from fussballdb.api import app

client = TestClient(app)


def test_predict_and_form():
    p = client.get("/predict", params={"home": "Freiburg", "away": "Bayern"}).json()
    assert abs(p["p_home"] + p["p_draw"] + p["p_away"] - 1) < 0.01
    form = client.get("/teams/BVB/form", params={"last_n": 3}).json()
    assert len(form["spiele"]) == 3


def test_lists():
    assert len(client.get("/teams").json()) == 18
    assert len(client.get("/table").json()) == 18
    assert client.get("/upcoming").status_code == 200


def test_errors():
    assert client.get("/teams/Gibtsnicht/form").status_code == 400
    assert client.post("/sql", json={"query": "DELETE FROM team"}).status_code == 400


def test_matchday_history():
    seasons = client.get("/seasons").json()
    assert {s["start_year"] for s in seasons} >= {2023, 2024, 2025, 2026}
    md = client.get("/matchday/2025/10").json()
    assert len(md["games"]) == 9
    g = md["games"][0]
    assert g["basis"] == "rueckblick" and g["tip_home"] is not None and g["points"] in (0, 2, 3, 4)
    # Rückblick-Prognose darf nur Daten bis zum Anpfiff des ersten Spiels nutzen
    assert g["as_of"] <= min(x["kickoff"] for x in md["games"])
    assert client.get("/matchday/2025/99").status_code == 400


def test_status():
    st = client.get("/status").json()
    assert "running" in st["update"]
    assert {c["step"] for c in st["checks"]} >= {"ergebnisse", "prognosen", "ausfaelle"}


def test_match_detail():
    md = client.get("/matchday/2025/10").json()
    g = md["games"][0]
    d = client.get(f"/match/{g['id']}").json()
    assert d["game"]["id"] == g["id"] and d["game"]["tip_home"] == g["tip_home"]
    # Form nur aus Spielen vor diesem Spiel, das jüngste zuerst
    for side in ("home", "away"):
        kickoffs = [f["kickoff"] for f in d["form"][side]]
        assert 0 < len(kickoffs) <= 6 and all(k < d["game"]["kickoff"] for k in kickoffs)
        assert kickoffs == sorted(kickoffs, reverse=True)
    s = d["h2h_summary"]
    assert s["spiele"] == len(d["h2h"]) == s["siege_heim"] + s["remis"] + s["siege_gast"]
    assert g["id"] not in {x["id"] for x in d["h2h"]}
    assert d["statistik"]["home"]["goals"] == g["home_goals"]
    assert d["ausfaelle"] is None  # gespielt: keine aktuellen Ausfälle
    assert client.get("/match/0").status_code == 400


def test_comp_match_detail():
    for comp in ("CL", "D2", "DFB"):
        rnd = client.get(f"/eu/{comp}/round/2025/1").json()
        g = rnd["games"][0]
        d = client.get(f"/eu/{comp}/match/{g['id']}").json()
        assert d["game"]["id"] == g["id"] and d["wettbewerb"] == rnd["wettbewerb"]
        assert all(f["kickoff"] < d["game"]["kickoff"] and f["wettbewerb"] for f in d["form"]["home"])
        assert (d["tabelle"] is None) == (comp == "DFB")
    # falscher Wettbewerb zum Spiel
    assert client.get(f"/eu/D2/match/{g['id']}").status_code == 400


def test_history_seasons():
    """Ältere Saisons sind abrufbar, das Modell sieht sie nicht."""
    from fussballdb.model.data import load_matches

    md = client.get("/matchday/1993/1").json()
    assert len(md["games"]) == 9 and all(g["p_home"] is None for g in md["games"])
    # 1993/94: zwei Punkte je Sieg, Meister Bayern mit 44 Punkten
    assert client.get("/table", params={"season": 1993}).json()[0] == {
        **client.get("/table", params={"season": 1993}).json()[0], "name": "FC Bayern München", "pkt": 44}
    assert load_matches()["season"].min() == 2014
    d = client.get(f"/match/{md['games'][0]['id']}").json()
    assert d["h2h"] == [] and d["form"]["home"] == []  # davor gibt es nichts


def test_venue_and_weather():
    """Spielort und Wetter je Spiel (laufende Saison); gespielte Spiele mit gemessenem Wetter."""
    seasons = client.get("/seasons").json()
    current = max(s["start_year"] for s in seasons)
    games = client.get(f"/matchday/{current}/1").json()["games"]
    ort = games[0]["ort"]
    assert ort["stadion"] and ort["kapazitaet"] > 1000
    assert ort["wetter"]["art"] == "gemessen" and ort["wetter"]["temp_c"] is not None
    assert client.get("/matchday/2020/1").json()["games"][0]["ort"] is None  # ältere Saisons ohne Spielort


def test_matchday_order_like_kicktipp():
    """Spiele eines Spieltags in der Reihenfolge von Kicktipp, sofern geladen (match.kicktipp_pos)."""
    from fussballdb.assistant.tools import _rows

    current = max(s["start_year"] for s in client.get("/seasons").json())
    pos = {r["id"]: r["kicktipp_pos"] for r in _rows(
        "SELECT m.id, m.kicktipp_pos FROM match m JOIN season s ON s.id = m.season_id "
        "WHERE s.start_year = :y AND m.matchday = 1", y=current)}
    if not all(pos.values()):
        return  # ohne Tipprunde mit öffentlichem Spielplan gibt es keine Reihenfolge
    ids = [g["id"] for g in client.get(f"/matchday/{current}/1").json()["games"]]
    assert [pos[i] for i in ids] == sorted(pos.values())


def test_match_reports():
    """Spielberichte: Schlagzeile, Vorspann mit Ergebnis, Tore im Text ohne Modellsprache, Suche filtert nach Team."""
    md = client.get("/matchday/2025/10").json()
    g = next(x for x in md["games"] if x["home_goals"] + x["away_goals"] > 0)
    lines = client.get(f"/match/{g['id']}").json()["bericht"].splitlines()
    assert f"{g['home']} – {g['away']} {g['home_goals']}:{g['away_goals']} (" in lines[1]
    assert "Minute" in lines[2] and "Modell" not in "\n".join(lines)
    hits = client.get("/reports/search", params={"q": "Comeback", "team": "Gladbach", "limit": 3}).json()
    assert hits and all("Mönchengladbach" in h["bericht"].splitlines()[1] for h in hits)
