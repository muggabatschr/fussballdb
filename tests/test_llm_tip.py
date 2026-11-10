from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np

from fussballdb.model.llm_tip import _llm_p, _news, _rescaled, _table

KICK = datetime(2026, 11, 8, 14, 30, tzinfo=timezone.utc)


def item(title, hours_before):
    return SimpleNamespace(title=title, published_at=KICK - timedelta(hours=hours_before))


def test_news_only_well_before_kickoff_and_without_result():
    items = [item("Einfallslose Kölner unterliegen Leverkusen im Derby", 0.05),  # umgeschriebener Vorbericht
             item("Podolski vermisst beim FC Köln etwas Entscheidendes", 30),
             item("2:4 gegen Stuttgart: Einzelkritik", 40),  # Ergebnis im Titel
             item("Köln gegen Leverkusen live im TV und Stream", 30),  # TV-Hinweis
             item("Uralte Meldung", 24 * 5)]
    assert _news(items, KICK) == ["Podolski vermisst beim FC Köln etwas Entscheidendes"]


def test_rescaled_keeps_shape_and_hits_target():
    m = np.array([[0.1, 0.1], [0.4, 0.4]])  # Heimsieg 0,4, Remis 0,5, Auswärtssieg 0,1
    out = _rescaled(m, np.array([0.6, 0.3, 0.1]))
    i, j = np.indices(out.shape)
    assert abs(out[i > j].sum() - 0.6) < 1e-9 and abs(out[i == j].sum() - 0.3) < 1e-9
    assert abs(out[0, 0] / out[1, 1] - 0.25) < 1e-9  # innerhalb einer Tendenz bleibt das Verhältnis


def test_llm_probabilities_normalised_and_percent():
    assert np.allclose(_llm_p({"p_heim": 50, "p_remis": 25, "p_gast": 25}, (0.4, 0.3, 0.3)), [0.5, 0.25, 0.25])
    assert np.allclose(_llm_p({"p_heim": 0, "p_remis": 0, "p_gast": 0}, (0.4, 0.3, 0.3)), [0.4, 0.3, 0.3])


def test_table_only_games_before_kickoff():
    rows = [SimpleNamespace(kickoff=KICK - timedelta(days=7), h=1, a=2, hg=2, ag=0),
            SimpleNamespace(kickoff=KICK, h=2, a=1, hg=5, ag=0)]  # das Spiel selbst zählt nicht
    t = _table(rows, KICK)
    assert t[1]["punkte"] == 3 and t[2]["punkte"] == 0 and t[1]["platz"] == 1
