from datetime import datetime, timezone

from fussballdb.ingest.sportschau import match_up, parse_list, parse_players, parse_team_stats

LIST = """<ul><li data-match_id="12194023" data-datetime="2026-09-19T13:30:00Z" data-sport_id="1" class="even finished match match-4">
<div class="team-image team-image-home hs-winner team-autoimage"><img src="https://s.hs-data.com/gfx/emblem/common/80x80/943.png"/></div>
<div class="team-name team-name-home hs-winner">Hamburger SV</div><div class="team-shortname team-shortname-home hs-winner">Hamburg</div>
<div class="team-image team-image-away team-autoimage"><img src="https://s.hs-data.com/gfx/emblem/common/80x80/9.png"/></div>
<div class="team-shortname team-shortname-away">Köln</div><div class="team-name team-name-away">1. FC Köln</div>
<div class="match-more"><a href="/live-und-ergebnisse/fussball/deutschland-bundesliga/ma12194023/hamburger-sv_1-fc-koeln/liveticker"></a></div></li>
<li data-match_id="12194038" data-datetime="2026-12-06T12:30:00Z" class="odd match match-5">
<div class="team-name team-name-home">SV Werder Bremen</div><div class="team-name team-name-away">FC Augsburg</div>
<a href="/live-und-ergebnisse/fussball/deutschland-bundesliga/ma12194038/werder-bremen_fc-augsburg/info"></a></li></ul>"""

TEAM = """<ul class="hs-comparison hs-comparison-team "><li class="team_stats-tracking_distance team_stats-tracking_distance-format">
<div class="hs-name">km</div><div class="hs-value hs-value-home">113,56 km</div><svg></svg><div class="hs-value hs-value-away">111,74 km</div></li>
<li class="team_stats-tracking_sprints team_stats-tracking_sprints-"><div class="hs-value hs-value-home">143</div><div class="hs-value hs-value-away">136</div></li>
<li class="team_stats-balls_touched_percentage team_stats-balls_touched_percentage-format"><div class="hs-value hs-value-home">36,63 %</div><div class="hs-value hs-value-away">63,37 %</div></li>
<li class="team_stats-passes team_stats-passes-"><div class="hs-value hs-value-home">1.272</div><div class="hs-value hs-value-away">576</div></li>
<li class="team_stats-card_yellow team_stats-card_yellow-"><div class="hs-value hs-value-home">2</div><div class="hs-value hs-value-away">3</div></li></ul>"""

PLAYERS = """<table><tbody><tr class="odd first last entry entry-1" data-team_id="9" data-competition_id="12">
<td class="person-name person-name-list"><a href="/x">Ellyes Skhiri</a></td><td class="person_stats-playing_minutes person_stats-playing_minutes-list">90</td>
<td class="person_stats-tracking_distance person_stats-tracking_distance-format hs-sorted-value">12,61</td></tr>
<tr class="even middle entry entry-2" data-team_id="943" data-competition_id="12">
<td class="person-name person-name-list"><a href="/y">Fábio Vieira</a></td><td class="person_stats-playing_minutes person_stats-playing_minutes-list">77</td>
<td class="person_stats-tracking_distance person_stats-tracking_distance-format hs-sorted-value">10,53</td></tr></tbody></table>"""


def test_parse_list_reads_teams_kickoff_status_and_emblems():
    games = parse_list(LIST)
    assert [g["id"] for g in games] == [12194023, 12194038]
    hsv = games[0]
    assert hsv["finished"] and not games[1]["finished"]
    assert hsv["home"] == ["Hamburger SV", "Hamburg"] and hsv["away"] == ["Köln", "1. FC Köln"]
    assert hsv["kickoff"] == datetime(2026, 9, 19, 13, 30, tzinfo=timezone.utc)
    assert hsv["path"].endswith("/ma12194023/hamburger-sv_1-fc-koeln")
    assert (hsv["home_team"], hsv["away_team"]) == ("943", "9")


def test_team_stats_parse_german_numbers_and_skip_unknown_keys():
    home, away = parse_team_stats(TEAM)
    assert home == {"distance_km": 113.56, "sprints": 143, "possession": 36.63, "passes": 1272}
    assert away["distance_km"] == 111.74 and away["possession"] == 63.37


def test_players_keep_team_and_minutes():
    rows = parse_players(PLAYERS, "tracking_distance")
    assert rows[0] == {"player": "Ellyes Skhiri", "team": "9", "minutes": 90, "value": 12.61}
    assert rows[1]["player"] == "Fábio Vieira" and rows[1]["team"] == "943"


def test_match_up_uses_kickoff_window_and_names():
    theirs = parse_list(LIST)
    ours = [{"id": 1, "kickoff": datetime(2026, 9, 19, 15, 30, tzinfo=timezone.utc), "home": "Hamburger SV", "away": "1. FC Köln"},
            {"id": 2, "kickoff": datetime(2026, 9, 19, 15, 30, tzinfo=timezone.utc), "home": "SV Werder Bremen", "away": "FC Augsburg"}]
    assert {k: v["id"] for k, v in match_up(ours, theirs).items()} == {1: 12194023}  # Bremen liegt Monate daneben
