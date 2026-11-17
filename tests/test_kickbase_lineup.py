import pandas as pd

from fussballdb.features.kickbase_lineup import best_lineup, current_lineup, swaps


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


def player(pid, pos, pts, ausfall=None, lo=None, mw=10e6, preis=None):
    return {"player_id": pid, "name": f"P{pid}", "position": pos, "team_name": "X", "kb_punkte": pts,
            "einsatz": 1.0, "gegner": ["Y"], "ausfall": ausfall, "lineup_pos": lo, "marktwert": mw,
            "markt_preis": preis}


def squad():
    rows = [player(1, "TW", 50, lo=0)] + [player(10 + i, "ABW", 40, lo=1 + i) for i in range(4)]
    rows += [player(20 + i, "MF", 60, lo=5 + i) for i in range(4)] + [player(30, "ST", 70, lo=9)]
    rows += [player(31, "ST", 0, ausfall="injury", lo=10)]
    return pd.DataFrame(rows)


def test_empty_slot_when_not_enough_fit_players():
    out = best_lineup(squad())
    assert out["formation"] and sum(out["fehlt"].values()) == 1  # nur 10 fitte Feldspieler + Torwart


def test_current_lineup_counts_injured_as_zero():
    now = current_lineup(squad())
    assert now["formation"] == "4-4-2" and now["punkte"] == 50 + 160 + 240 + 70


def test_swap_can_change_formation_and_respects_budget():
    market = pd.DataFrame([player(40, "ST", 80, preis=5e6), player(41, "ST", 90, preis=50e6)])
    out = swaps(squad(), market, money=0.0)
    assert out and out[0]["kauf"] == "P40"  # P41 wäre besser, ist aber nicht bezahlbar
    assert all(s["budget_danach"] >= 0 for s in out)
