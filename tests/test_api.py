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
