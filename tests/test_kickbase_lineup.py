import pandas as pd

from fussballdb.features.kickbase_lineup import best_lineup


def _p(i, pos, pts, ausfall=None):
    return {"player_id": i, "name": f"S{i}", "position": pos, "team_name": "X", "kb_punkte": pts, "einsatz": 1.0,
            "gegner": ["Y"], "ausfall": ausfall}


def test_best_formation_and_injured_players():
    squad = pd.DataFrame([_p(1, "TW", 50), _p(2, "TW", 40)]
                         + [_p(10 + i, "ABW", 60 - i) for i in range(5)]
                         + [_p(20 + i, "MF", 70 - i) for i in range(4)]
                         + [_p(30 + i, "ST", 100 - i) for i in range(3)] + [_p(40, "ST", 200, "injury")])
    res = best_lineup(squad)
    # 3 starke Stürmer, 4 Mittelfeldspieler, 3 Abwehr schlagen jede Formation mit mehr Abwehr
    assert res["formation"] == "3-4-3"
    assert len(res["elf"]) == 11 and {"S1"} <= {x["name"] for x in res["elf"]}
    assert "S40" not in {x["name"] for x in res["elf"]}
    assert res["ausfaelle"][0]["name"] == "S40"
