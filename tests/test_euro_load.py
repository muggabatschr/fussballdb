import pandas as pd

from fussballdb.features.euro_load import apply


def test_euro_load_only_within_window():
    schedule = {1: [(pd.Timestamp("2026-10-20 19:00", tz="UTC"), "CL")]}
    base = {"attack_mult": 0.95, "concede_mult": 1.0}
    tired = apply(base, 1, pd.Timestamp("2026-10-23 18:30", tz="UTC"), schedule)
    assert abs(tired["attack_mult"] - 0.95 * 0.9) < 1e-9
    assert tired["euro_load"] == {"tage": 3, "wettbewerb": "CL", "faktor": 0.9}
    # fünf Tage später oder anderes Team: keine Belastung, Eingabe unverändert
    assert apply(base, 1, pd.Timestamp("2026-10-25 18:30", tz="UTC"), schedule) is base
    assert apply(base, 2, pd.Timestamp("2026-10-23 18:30", tz="UTC"), schedule) is base
    # Europapokalspiel nach dem Bundesliga-Spiel zählt nicht
    assert apply(base, 1, pd.Timestamp("2026-10-19 18:30", tz="UTC"), schedule) is base
