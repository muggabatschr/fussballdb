"""Spielort (Stadion, Stadt, Kapazität, Koordinaten) je Spiel von den FotMob-Spielseiten, für Bundesliga,
2. Bundesliga, DFB-Pokal und Champions League ab der laufenden Saison.

FotMob nennt den echten Spielort auch bei Ausweichstadien (Schachtar 2024/25 in Gelsenkirchen) und Finals.
Offene Spiele werden bei jedem Lauf neu geladen, gespielte einmal danach und dann eingefroren: so bleiben
Name und Kapazität, wie sie am Spieltag waren, auch wenn ein Stadion später umbenannt oder umgebaut wird.
Ältere Spiele haben keinen Spielort (Wikidata kennt Sponsorennamen nicht mit Zeitraum)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.config import DEFAULT_SEASONS
from fussballdb.db.models import MatchVenue
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.cl_xg import MATCH, _next_data
from fussballdb.ingest.http import get_text
from fussballdb.ingest.tv import _similarity
from fussballdb.ingest.upsert import upsert

# unsere Kennung -> FotMob-Wettbewerb (ID und Pfad der Spielplan-Seite)
LEAGUES = {"BL": (54, "bundesliga"), "D2": (146, "2-bundesliga"), "DFB": (209, "dfb-pokal"),
           "CL": (42, "champions-league")}
FIXTURES = "https://www.fotmob.com/leagues/{id}/fixtures/{slug}?season={season}-{next}"
AHEAD = timedelta(days=14)  # offene Spiele so weit im Voraus


def _candidates(session: Session, comp: str, season: int) -> list[tuple]:
    """Spiele der Saison ohne eingefrorenen Spielort: (id, Anstoß, beendet, Heimnamen, Gastnamen)."""
    if comp == "BL":
        sql = """
            SELECT m.id, m.kickoff, m.finished,
                   string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            LEFT JOIN team_alias ha ON ha.team_id = ht.id LEFT JOIN team_alias aa ON aa.team_id = at.id
            WHERE s.start_year = :y
              AND NOT EXISTS (SELECT 1 FROM match_venue v WHERE v.competition = 'BL' AND v.match_id = m.id AND v.frozen)
            GROUP BY m.id, m.kickoff, m.finished, ht.name, at.name"""
    else:
        sql = """
            SELECT m.id, m.kickoff, m.finished,
                   string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
            FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
            LEFT JOIN eu_team_alias ha ON ha.team_id = ht.id LEFT JOIN eu_team_alias aa ON aa.team_id = at.id
            WHERE m.competition = :c AND m.season = :y
              AND NOT EXISTS (SELECT 1 FROM match_venue v WHERE v.competition = :c AND v.match_id = m.id AND v.frozen)
            GROUP BY m.id, m.kickoff, m.finished, ht.name, at.name"""
    return session.execute(text(sql), {"y": season, "c": comp}).all()


def _fixtures(comp: str, season: int) -> list[dict]:
    league_id, slug = LEAGUES[comp]
    html = get_text(FIXTURES.format(id=league_id, slug=slug, season=season, next=season + 1), headers=BROWSER_HEADERS)
    out = []
    for m in _next_data(html).get("fixtures", {}).get("allMatches", []):
        status = m.get("status", {})
        if status.get("cancelled") or not status.get("utcTime"):
            continue
        out.append({"id": int(m["id"]), "home": m["home"]["name"], "away": m["away"]["name"],
                    "kickoff": datetime.fromisoformat(status["utcTime"].replace("Z", "+00:00"))})
    return out


def stadium(fotmob_id: int, finished: bool) -> dict | None:
    """Spielort laut FotMob-Spielseite; gespielte Spiele aus dem Zwischenspeicher, offene immer frisch."""
    html = get_text(MATCH.format(id=fotmob_id), headers=BROWSER_HEADERS, cache=finished, delay=1.0)
    return ((_next_data(html).get("content") or {}).get("matchFacts") or {}).get("infoBox", {}).get("Stadium")


def ingest(session: Session, season: int | None = None, log=print) -> dict:
    """Spielorte für gespielte Spiele der Saison (einmal, dann eingefroren) und offene der nächsten 14 Tage."""
    season = season or max(DEFAULT_SEASONS)
    now = datetime.now(timezone.utc)
    rows, unmatched = [], []
    for comp in LEAGUES:
        todo = [c for c in _candidates(session, comp, season) if c[2] or c[1] <= now + AHEAD]
        if not todo:
            continue
        done = set(session.scalars(text("SELECT fotmob_id FROM match_venue WHERE competition = :c AND frozen"), {"c": comp}))
        for fx in _fixtures(comp, season):
            if fx["id"] in done:
                continue
            # gleicher Anstoß, oder gleicher Tag mit klar passenden Namen (Uhrzeit offen oder Anpfiff verschoben)
            near = [c for c in todo if c[1].date() == fx["kickoff"].date()]
            scored = [(_similarity(fx["home"], c[3]) + _similarity(fx["away"], c[4]), c) for c in near]
            best = max(scored, default=None, key=lambda x: x[0])
            if best is None:
                continue  # schon eingefroren oder nicht in den nächsten 14 Tagen
            if best[0] < (1.0 if best[1][1] == fx["kickoff"] else 1.6):
                unmatched.append(f"{comp} {fx['home']} – {fx['away']}")
                continue
            match_id, _, finished = best[1][0], best[1][1], best[1][2]
            st = stadium(fx["id"], finished)
            todo = [c for c in todo if c[0] != match_id]
            if not st or not st.get("name"):
                continue
            rows.append({"competition": comp, "match_id": match_id, "fotmob_id": fx["id"], "stadium": st["name"],
                         "city": st.get("city"), "country": st.get("country"), "capacity": st.get("capacity") or None,
                         "lat": st.get("lat"), "lon": st.get("long"), "frozen": finished, "fetched_at": now})
            if len(rows) % 50 == 0:
                log(f"  {len(rows)} Spielorte")
    upsert(session, MatchVenue, rows, ["competition", "match_id"])
    return {"spielorte": len(rows), "nicht_zugeordnet": sorted(set(unmatched))}


def for_matches(competition: str, match_ids: list[int]) -> dict[int, dict]:
    """Match-ID -> {"stadion", "stadt", "land", "kapazitaet", "wetter"} für API und Web. wetter: art
    (vorhersage | gemessen), temp_c, regen_mm, regen_pct (nur Vorhersage), wind_kmh, code (WMO)."""
    from fussballdb.db.session import engine

    if not match_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT v.match_id, v.stadium, v.city, v.country, v.capacity,
                   w.kind, w.temp_c, w.precip_mm, w.precip_prob, w.wind_kmh, w.weather_code
            FROM match_venue v
            LEFT JOIN match_weather w ON w.competition = v.competition AND w.match_id = v.match_id
            WHERE v.competition = :c AND v.match_id = ANY(:ids)"""), {"c": competition, "ids": list(match_ids)}).all()
    out = {}
    for r in rows:
        out[r.match_id] = {"stadion": r.stadium, "stadt": r.city, "land": r.country, "kapazitaet": r.capacity,
                           "wetter": None if r.kind is None else {
                               "art": r.kind, "temp_c": r.temp_c, "regen_mm": r.precip_mm, "regen_pct": r.precip_prob,
                               "wind_kmh": r.wind_kmh, "code": r.weather_code}}
    return out
