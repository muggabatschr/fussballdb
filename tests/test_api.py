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
