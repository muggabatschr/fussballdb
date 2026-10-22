import pandas as pd

from fussballdb.model import cl_table


def test_league_phase_table_with_model_place_and_projection(monkeypatch):
    def game(h, a, hg=None, ag=None, ph=0.5, pd_=0.25, pa=0.25):
        return {"home": h, "away": a, "hg": hg, "ag": ag, "finished": hg is not None,
                "p_home": ph, "p_draw": pd_, "p_away": pa, "eh": 1.5, "ea": 1.0}

    df = pd.DataFrame([
        game("A", "B", 0, 2, ph=0.8, pd_=0.15, pa=0.05),  # Überraschung: B gewinnt als Außenseiter
        game("C", "D", 1, 1),
        game("A", "D", ph=0.97, pd_=0.02, pa=0.01),  # offen
        game("B", "C", ph=0.01, pd_=0.02, pa=0.97),  # offen
    ])
    monkeypatch.setattr(cl_table, "_load", lambda *args: df)
    rows = {r["name"]: r for r in cl_table.table(2026, "CL", n=2000)}
    assert rows["B"]["platz"] == 1 and rows["A"]["platz"] == 4
    assert rows["B"]["platz_diff"] > 0 and rows["A"]["platz_diff"] < 0  # B steht besser als erwartet, A schlechter
    assert abs(sum(r["p_achtelfinale"] for r in rows.values()) - 400) < 1  # 4 Teams, alle unter den ersten 8
    assert rows["A"]["erw_punkte"] > rows["A"]["pkt"] + 2.5
