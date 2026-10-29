"""Spielort (Stadion, Stadt, Kapazität, Koordinaten) je Spiel von den FotMob-Spielseiten, für Bundesliga,
2. Bundesliga, DFB-Pokal und Champions League ab der laufenden Saison.

FotMob nennt den echten Spielort auch bei Ausweichstadien (Schachtar 2024/25 in Gelsenkirchen) und Finals.
Offene Spiele werden bei jedem Lauf neu geladen, gespielte einmal danach und dann eingefroren: so bleiben
Name und Kapazität, wie sie am Spieltag waren, auch wenn ein Stadion später umbenannt oder umgebaut wird.
Ältere Spiele haben keinen Spielort (Wikidata kennt Sponsorennamen nicht mit Zeitraum)."""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

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
           "CL": (42, "champions-league"), "BRA": (268, "serie-a")}
CALENDAR_YEAR = ("BRA",)  # Saison = Kalenderjahr (FotMob: season=2026 statt 2026-2027)
FIXTURES = "https://www.fotmob.com/leagues/{id}/fixtures/{slug}?season={season}-{next}"
AHEAD = timedelta(days=14)  # offene Spiele so weit im Voraus

# Anreise: Google-Maps-Link mit ÖPNV und "Ankunft bis" eine Stunde vor dem Anpfiff. Das Format mit Uhrzeit
# (data=…!6e1!8j<Zeit>!3e3) ist nicht offiziell dokumentiert, Google nutzt es aber selbst für seine Links;
# die Zeit ist die Ortszeit am Stadion, kodiert als Sekunden seit 1970 (als wäre sie UTC).
ARRIVE_BEFORE = timedelta(hours=1)
ROUTE = "https://www.google.com/maps/dir/{start}/{lat},{lon}/data=!4m6!4m5!2m3!6e1!7e2!8j{ts}!3e3"
ROUTE_PLAIN = "https://www.google.com/maps/dir/?api=1&destination={lat},{lon}&travelmode=transit"
# Zeitzone je Land laut FotMob; ohne Eintrag Mitteleuropa
COUNTRY_TZ = {"England": "Europe/London", "Scotland": "Europe/London", "Wales": "Europe/London",
              "Northern Ireland": "Europe/London", "Ireland": "Europe/Dublin", "Portugal": "Europe/Lisbon",
              "Greece": "Europe/Athens", "Cyprus": "Asia/Nicosia", "Romania": "Europe/Bucharest",
              "Bulgaria": "Europe/Sofia", "Ukraine": "Europe/Kyiv", "Moldova": "Europe/Chisinau",
              "Finland": "Europe/Helsinki", "Israel": "Asia/Jerusalem", "Türkiye": "Europe/Istanbul",
              "Turkey": "Europe/Istanbul", "Azerbaijan": "Asia/Baku", "Kazakhstan": "Asia/Almaty",
              "Russia": "Europe/Moscow", "Georgia": "Asia/Tbilisi", "Armenia": "Asia/Yerevan",
              "Brazil": "America/Sao_Paulo"}  # Série A fast nur UTC−3 (Cuiabá UTC−4 bleibt eine Stunde daneben)


def route(lat: float, lon: float, kickoff: datetime, country: str | None, start: str = "") -> dict:
    """Anreise-Links: `url` mit Ankunft eine Stunde vor dem Anpfiff (Start leer = in der Google-Maps-App der
    aktuelle Standort; `start` z. B. "Stuttgart Hbf" oder "48.78,9.18"), `url_vorlage` mit {start} für das Web,
    `url_ohne_zeit` im offiziell dokumentierten Format als Rückfall."""
    local = (kickoff - ARRIVE_BEFORE).astimezone(ZoneInfo(COUNTRY_TZ.get(country or "", "Europe/Berlin")))
    wall = int(local.replace(tzinfo=timezone.utc).timestamp())
    lat_s, lon_s = f"{lat:.5f}", f"{lon:.5f}"
    template = ROUTE.format(start="{start}", lat=lat_s, lon=lon_s, ts=wall)
    return {"ankunft": local.isoformat(timespec="minutes"), "url": template.replace("{start}", quote(start)),
            "url_vorlage": template, "url_ohne_zeit": ROUTE_PLAIN.format(lat=lat_s, lon=lon_s)}


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


def pair(fx: dict, todo: list[tuple]) -> tuple | None | bool:
    """Unser Spiel (aus _candidates) zu einem FotMob-Spiel: gleicher Anstoß, oder gleicher Tag mit klar passenden
    Namen (Uhrzeit offen oder Anpfiff verschoben), ohne Spiel an dem Tag auch ±1 Tag bei sehr klaren Namen.
    None = kein Spiel an dem Tag, False = Namen passen nicht."""
    # Datum beider Seiten in UTC (die Datenbank liefert Berliner Zeit; brasilianische Abendspiele um 23 Uhr UTC
    # lägen sonst an verschiedenen Tagen)
    day = fx["kickoff"].astimezone(timezone.utc).date()
    near = [c for c in todo if c[1].astimezone(timezone.utc).date() == day]
    if not near:  # Datum weicht um einen Tag ab (Hannover – Darmstadt 2024/25): nur bei sehr klaren Namen
        near = [c for c in todo if abs((c[1].astimezone(timezone.utc).date() - day).days) == 1]
        scored = [(_similarity(fx["home"], c[3]) + _similarity(fx["away"], c[4]), c) for c in near]
        best = max(scored, default=None, key=lambda x: x[0])
        return best[1] if best and best[0] >= 1.8 else None
    scored = [(_similarity(fx["home"], c[3]) + _similarity(fx["away"], c[4]), c) for c in near]
    best = max(scored, default=None, key=lambda x: x[0])
    if best is None:
        return None
    return best[1] if best[0] >= (1.0 if best[1][1] == fx["kickoff"] else 1.6) else False


def _fixtures(comp: str, season: int) -> list[dict]:
    league_id, slug = LEAGUES[comp]
    url = FIXTURES.format(id=league_id, slug=slug, season=season, next=season + 1)
    if comp in CALENDAR_YEAR:
        url = url.split("?season=")[0] + f"?season={season}"
    html = get_text(url, headers=BROWSER_HEADERS)
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
        comp_season = now.year if comp in CALENDAR_YEAR else season
        todo = [c for c in _candidates(session, comp, comp_season) if c[2] or c[1] <= now + AHEAD]
        if not todo:
            continue
        done = set(session.scalars(text("SELECT fotmob_id FROM match_venue WHERE competition = :c AND frozen"), {"c": comp}))
        for fx in _fixtures(comp, comp_season):
            if fx["id"] in done:
                continue
            best = pair(fx, todo)
            if best is None:
                continue  # schon eingefroren oder nicht in den nächsten 14 Tagen
            if best is False:
                unmatched.append(f"{comp} {fx['home']} – {fx['away']}")
                continue
            match_id, finished = best[0], best[2]
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
    """Match-ID -> {"stadion", "stadt", "land", "kapazitaet", "wetter", "anreise"} für API und Web. wetter: art
    (vorhersage | gemessen), temp_c, regen_mm, regen_pct (nur Vorhersage), wind_kmh, code (WMO); anreise nur
    bei offenen Spielen (siehe route)."""
    from fussballdb.db.session import engine

    if not match_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT v.match_id, v.stadium, v.city, v.country, v.capacity, v.lat, v.lon,
                   coalesce(m.kickoff, e.kickoff) AS kickoff, coalesce(m.finished, e.finished) AS finished,
                   w.kind, w.temp_c, w.precip_mm, w.precip_prob, w.wind_kmh, w.weather_code
            FROM match_venue v
            LEFT JOIN match m ON v.competition = 'BL' AND m.id = v.match_id
            LEFT JOIN eu_match e ON v.competition <> 'BL' AND e.id = v.match_id
            LEFT JOIN match_weather w ON w.competition = v.competition AND w.match_id = v.match_id
            WHERE v.competition = :c AND v.match_id = ANY(:ids)"""), {"c": competition, "ids": list(match_ids)}).all()
    out = {}
    for r in rows:
        out[r.match_id] = {"stadion": r.stadium, "stadt": r.city, "land": r.country, "kapazitaet": r.capacity,
                           "wetter": None if r.kind is None else {
                               "art": r.kind, "temp_c": r.temp_c, "regen_mm": r.precip_mm, "regen_pct": r.precip_prob,
                               "wind_kmh": r.wind_kmh, "code": r.weather_code},
                           "anreise": route(r.lat, r.lon, r.kickoff, r.country)
                           if r.lat is not None and not r.finished else None}
    return out
