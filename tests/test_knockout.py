from fussballdb.model.knockout import advance, extra_time


def test_extra_time_sums_to_one_and_favours_stronger_team():
    h, d, a = extra_time(2.4, 0.6)
    assert abs(h + d + a - 1) < 1e-9 and h > a


def test_advance_adds_draw_share_to_90_minute_win():
    w = advance(0.34, 0.24, 0.42, 1.5, 1.7)
    assert abs(w["home"] + w["away"] - 1) < 1e-9
    assert 0.34 < w["home"] < 0.34 + 0.24 and w["verlaengerung"] == 0.24
    assert 0 < w["elfmeterschiessen"] < 0.24
    # gleich starke Teams: 50:50
    assert abs(advance(0.37, 0.26, 0.37, 1.3, 1.3)["home"] - 0.5) < 1e-9
