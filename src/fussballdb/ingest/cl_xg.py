"""xG der Spiele in Champions League, 2. Bundesliga und DFB-Pokal von FotMob (Spielliste je Saison, dann die
Spielseiten der gespielten Spiele). Zuordnung zu eu_match über Anstoßzeit und Teamnamen wie bei den Spielorten
(venues.pair). FotMob hat xG für die CL ab 2024/25, für 2. Liga und Pokal ab 2022/23, im Pokal auch bei
Amateurteams."""

import json
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.http import get_text

MATCH = "https://www.fotmob.com/match/{id}"


def _next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("FotMob: Seitenaufbau hat sich geändert (__NEXT_DATA__ fehlt)")
    return json.loads(m.group(1))["props"]["pageProps"]


def match_xg(fotmob_id: int) -> tuple[float, float] | None:
    """Team-xG eines Spiels (Statistik "expected_goals", gesamte Spielzeit)."""
    html = get_text(MATCH.format(id=fotmob_id), headers=BROWSER_HEADERS, cache=True, delay=1.5)
    stats = (_next_data(html).get("content", {}).get("stats") or {}).get("Periods", {}).get("All", {}).get("stats", [])
    for group in stats:
        for st in group.get("stats", []):
            values = st.get("stats") or []
            if st.get("key") == "expected_goals" and len(values) == 2 and None not in values:
                return float(values[0]), float(values[1])
    return None


COMPETITIONS = ("CL", "D2", "DFB")
FIRST_SEASON = {"CL": 2024, "D2": 2022, "DFB": 2022}


def ingest(session: Session, seasons: list[int], comps=COMPETITIONS, log=print) -> dict:
    """xG für gespielte Spiele ohne xG nachtragen. Liefert Anzahl und nicht zuordenbare Spiele."""
    from fussballdb.ingest.venues import _fixtures, pair

    found, unmatched, no_xg = 0, [], 0
    for comp in comps:
        for season in seasons:
            if season < FIRST_SEASON[comp]:
                continue
            todo = session.execute(text("""
                SELECT m.id, m.kickoff, m.finished,
                       string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
                FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
                LEFT JOIN eu_team_alias ha ON ha.team_id = ht.id LEFT JOIN eu_team_alias aa ON aa.team_id = at.id
                WHERE m.competition = :c AND m.season = :y AND m.finished AND m.home_xg IS NULL
                GROUP BY m.id, m.kickoff, m.finished, ht.name, at.name"""), {"c": comp, "y": season}).all()
            if not todo:
                continue
            for fx in _fixtures(comp, season):
                if fx["kickoff"] > datetime.now(fx["kickoff"].tzinfo):
                    continue
                best = pair(fx, todo)
                if best is None:
                    continue  # schon mit xG oder nicht in unserer Datenbank
                if best is False:
                    unmatched.append(f"{comp} {fx['home']} – {fx['away']}")
                    continue
                todo = [c for c in todo if c[0] != best[0]]
                xg = match_xg(fx["id"])
                session.execute(text("UPDATE eu_match SET fotmob_id = :f, home_xg = :h, away_xg = :a WHERE id = :id"),
                                {"f": fx["id"], "h": xg[0] if xg else None, "a": xg[1] if xg else None, "id": best[0]})
                found += bool(xg)
                no_xg += not xg
                if found and found % 50 == 0:
                    session.commit()
                    log(f"  {found} Spiele mit xG")
    return {"mit_xg": found, "ohne_xg": no_xg, "nicht_zugeordnet": sorted(set(unmatched))}
