from datetime import datetime

from fussballdb.ingest.lineups import BERLIN, parse_kickoff, parse_lineup, slugify

HTML = """
<div class="content"><div class="stadium_container_area"><p>So. 25.10.2026 | 17:30</p>
 <div class="player_position_row text-center"><div class="player_position_column">
   <div class="player_position_photo"><a href="/jonas-urbig_26101/"></a></div></div></div>
 <div class="player_position_row player_position_row2 text-center">
   <div class="player_position_column">
     <div class="sub_child"><div class="player_position_photo"><a href="/konrad-laimer_6324/"></a></div></div>
     <div class="sub_child"><div class="player_position_photo"><a href="/josip-stanisic_20102/"></a></div></div>
   </div>
   <div class="player_position_column"><div class="player_position_photo"><a href="/dayot-upamecano_11541/"></a></div></div>
 </div></div>
 <div class="team_squad_area"><a href="/sven-ulreich_205/"></a></div></div>
"""


def test_parse_lineup_roles():
    res = parse_lineup(HTML)
    assert res["kickoff"] == datetime(2026, 10, 25, 17, 30, tzinfo=BERLIN)
    roles = {slug: (role, row) for role, row, slug, _ in res["players"]}
    assert roles["jonas-urbig"] == ("start", 1)
    assert roles["konrad-laimer"] == ("start", 2)
    assert roles["josip-stanisic"] == ("alternative", 2)
    assert roles["dayot-upamecano"] == ("start", 2)
    assert roles["sven-ulreich"] == ("bank", None)


def test_relative_kickoff_and_slug():
    now = datetime(2026, 10, 19, 9, 0, tzinfo=BERLIN)
    assert parse_kickoff("Gestern 15:30", now) == datetime(2026, 10, 18, 15, 30, tzinfo=BERLIN)
    assert parse_kickoff("Morgen | 20:30", now) == datetime(2026, 10, 20, 20, 30, tzinfo=BERLIN)
    assert slugify("1. FC Köln") == "1-fc-koeln"
    assert slugify("FC Bayern München") == "fc-bayern-muenchen"
