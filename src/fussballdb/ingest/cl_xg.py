"""xG der Champions-League-Spiele von FotMob (Spielliste je Saison, dann die Spielseiten der gespielten
Spiele). Zuordnung zu eu_match über Anstoßzeit und Teamnamen wie beim TV-Programm."""

import json
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.http import get_text
from fussballdb.ingest.tv import _similarity

FIXTURES = "https://www.fotmob.com/leagues/42/fixtures/champions-league?season={season}-{next}"
MATCH = "https://www.fotmob.com/match/{id}"


def _next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("FotMob: Seitenaufbau hat sich geändert (__NEXT_DATA__ fehlt)")
    return json.loads(m.group(1))["props"]["pageProps"]


def fixtures(season: int) -> list[dict]:
    """Gespielte CL-Spiele einer Saison laut FotMob: id, Anstoß, Heim, Gast."""
    html = get_text(FIXTURES.format(season=season, next=season + 1), headers=BROWSER_HEADERS)
    out = []
    for m in _next_data(html).get("fixtures", {}).get("allMatches", []):
        status = m.get("status", {})
        if status.get("finished") and not status.get("cancelled"):
            out.append({"id": int(m["id"]), "home": m["home"]["name"], "away": m["away"]["name"],
                        "kickoff": datetime.fromisoformat(status["utcTime"].replace("Z", "+00:00"))})
    return out


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


def ingest(session: Session, seasons: list[int], log=print) -> dict:
    """xG für gespielte CL-Spiele ohne xG nachtragen. Liefert Anzahl und nicht zuordenbare Spiele."""
    rows = session.execute(text("""
        SELECT m.id, m.kickoff, m.home_xg,
               string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
        FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
        LEFT JOIN eu_team_alias ha ON ha.team_id = ht.id LEFT JOIN eu_team_alias aa ON aa.team_id = at.id
        WHERE m.competition = 'CL' AND m.finished AND m.season = ANY(:s)
        GROUP BY m.id, m.kickoff, m.home_xg, ht.name, at.name"""), {"s": seasons}).all()
    missing = {r[0]: r for r in rows if r[2] is None}
    found, unmatched, no_xg = 0, [], 0
    for season in seasons:
        if not any(r[1].year in (season, season + 1) for r in missing.values()):
            continue
        for fx in fixtures(season):
            same_time = [r for r in missing.values() if r[1] == fx["kickoff"]]
            scored = [(_similarity(fx["home"], r[3]) + _similarity(fx["away"], r[4]), r) for r in same_time]
            best = max(scored, default=None, key=lambda x: x[0])
            if best is None:
                continue  # schon mit xG oder nicht in unserer Datenbank
            if best[0] < 1.0:
                unmatched.append(f"{fx['home']} – {fx['away']}")
                continue
            xg = match_xg(fx["id"])
            match_id = best[1][0]
            session.execute(text("UPDATE eu_match SET fotmob_id = :f, home_xg = :h, away_xg = :a WHERE id = :id"),
                            {"f": fx["id"], "h": xg[0] if xg else None, "a": xg[1] if xg else None, "id": match_id})
            missing.pop(match_id, None)
            found += bool(xg)
            no_xg += not xg
            if found and found % 50 == 0:
                session.commit()
                log(f"  {found} Spiele mit xG")
    return {"mit_xg": found, "ohne_xg": no_xg, "nicht_zugeordnet": sorted(set(unmatched))}
