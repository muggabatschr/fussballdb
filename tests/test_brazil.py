from datetime import datetime, timezone

from fussballdb.ingest.brazil import _learn_aliases


def _fm(day, home, away, hid, aid, hg, ag):
    return {"home": home, "away": away, "home_fm": hid, "away_fm": aid, "finished": True, "hg": hg, "ag": ag,
            "kickoff": datetime(2025, 5, day, 23, tzinfo=timezone.utc)}


def _fd(day, home, away, hg, ag):
    return {"home": home, "away": away, "hg": hg, "ag": ag, "kickoff": datetime(2025, 5, day, 20, tzinfo=timezone.utc)}


def test_aliases_from_shared_games_tolerate_date_shift():
    fm = [_fm(3, "Flamengo", "São Paulo", "1", "2", 2, 1), _fm(10, "Vasco da Gama", "Flamengo", "3", "1", 0, 0)]
    fd = [_fd(4, "Flamengo RJ", "Sao Paulo", 2, 1),  # FotMob 23 Uhr UTC, football-data schon am nächsten Tag
          _fd(10, "Vasco", "Flamengo RJ", 0, 0), _fd(10, "Santos", "Gremio", 0, 0)]
    assert _learn_aliases(fm, fd) == {"1": "Flamengo RJ", "2": "Sao Paulo", "3": "Vasco"}


def test_brazil_table_counts_wins_before_goal_difference():
    import numpy as np

    from fussballdb.model.cl_table import _rank

    points = np.array([10.0, 10.0])
    wins, gd = np.array([2.0, 3.0]), np.array([5.0, 1.0])
    assert list(_rank(points, wins * 1e3 + gd, np.zeros(2))) == [2, 1]  # mehr Siege schlägt bessere Tordifferenz
