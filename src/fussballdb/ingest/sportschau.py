"""Laufleistung, Sprints, Ballbesitz, Zweikämpfe und Pässe je Spiel von sportschau.de (Live & Ergebnisse).

- Teamwerte (Seite "Teamstatistik"): gelaufene Kilometer und Sprints (nur Bundesliga, Tracking der DFL, ab
  2014/15), Ballbesitz, gewonnene Zweikämpfe in %, Pässe und Passquote (Bundesliga, 2. Bundesliga, CL; im
  DFB-Pokal nur bei manchen Spielen, oft nur Ballbesitz).
- Spielerwerte (nur Bundesliga): Kilometer und Einsatzminuten je Spieler, Höchstgeschwindigkeit in km/h.

Die Spiele einer Saison stehen auf den Spieltags- bzw. Rundenseiten (Links in der Auswahlliste der
Saisonseite) mit Anstoß in UTC und beiden Teamnamen. Zugeordnet wird über den Anstoß (±36 Stunden) und die
ähnlichsten Namen. Gespielte Spiele werden einmal geladen, frühestens drei Stunden nach dem Anpfiff, und die
Seiten bleiben im Cache. Ein Spiel ohne Werte bekommt trotzdem Zeilen (leer), damit es nicht jedes Mal neu
abgefragt wird.

Die Seiten sind frei abrufbar; robots.txt sperrt nur KI-Crawler fürs Training, nicht den Abruf einzelner
Seiten. Abgefragt wird nacheinander (unter einer Seite je Sekunde) und nur für die private Nutzung.
"""

import difflib
import html as htmllib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.models import MatchExtraStats, PlayerTracking
from fussballdb.ingest.europe import _norm
from fussballdb.ingest.http import get_text
from fussballdb.ingest.upsert import upsert

BASE = "https://www.sportschau.de/live-und-ergebnisse/fussball"
# Wettbewerb (wie in match_page: BL → match, sonst eu_match) → Pfad bei der Sportschau
COMPS = {"BL": "deutschland-bundesliga", "D2": "deutschland-2-bundesliga", "DFB": "deutschland-dfb-pokal",
         "CL": "uefa-champions-league"}
FIRST_SEASON = {"BL": 2014, "D2": 2022, "DFB": 2024, "CL": 2024}  # so weit reichen unsere Spiele zurück
PLAYER_COMPS = ("BL",)  # Spieler-Laufdaten nur in der Bundesliga
AFTER = timedelta(hours=3)  # Werte stehen erst nach dem Abpfiff vollständig
DELAY = 0.3  # dazu ~0,5 s Antwortzeit bei älteren Seiten
MIN_SCORE = 1.2  # Summe der Namensähnlichkeit (Heim + Gast), darunter keine Zuordnung

# Teamstatistik: Schlüssel der Sportschau → Spalte
TEAM_KEYS = {"tracking_distance": "distance_km", "tracking_sprints": "sprints",
             "balls_touched_percentage": "possession", "duels_won_percentage": "duels_won_pct",
             "passes": "passes", "passes_complete_percentage": "pass_pct"}


def _num(s: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d{3})*(?:,\d+)?", s)
    return float(m.group(0).replace(".", "").replace(",", ".")) if m else None


def seasons(comp: str) -> dict[int, str]:
    """Startjahr → Pfadstück "se15388/2014-2015" aus der Auswahlliste der Wettbewerbsseite."""
    page = get_text(f"{BASE}/{COMPS[comp]}/spiele-und-ergebnisse")
    return {int(a): f"se{se}/{a}-{b}" for se, a, b in set(re.findall(r"se(\d+)/(\d{4})-(\d{4})", page))}


def parse_list(page: str) -> list[dict]:
    """Spiele einer Spieltags-/Rundenseite."""
    out = []
    for li in re.findall(r"<li data-match_id=.*?</li>", page, re.S):
        head = li.split(">", 1)[0]
        dt = re.search(r'data-datetime="([^"]+)"', head)
        link = re.search(r'href="(/live-und-ergebnisse/fussball/[^"]*/ma\d+/[^/"]+)/', li)
        names = {side: [htmllib.unescape(x) for x in re.findall(
            rf'class="team-(?:name|shortname) team-(?:name|shortname)-{side}[^"]*">([^<]+)<', li)] for side in ("home", "away")}
        emblems = re.findall(r"emblem/common/\d+x\d+/(\d+)\.png", li)
        if not dt or not link or not names["home"] or not names["away"]:
            continue
        out.append({"id": int(re.search(r'data-match_id="(\d+)"', head).group(1)),
                    "kickoff": datetime.fromisoformat(dt.group(1).replace("Z", "+00:00")),
                    "finished": bool(re.search(r'class="[^"]*\bfinished\b', head)),
                    "home": names["home"], "away": names["away"], "path": link.group(1),
                    "home_team": emblems[0] if len(emblems) > 0 else None,
                    "away_team": emblems[1] if len(emblems) > 1 else None})
    return out


def season_matches(comp: str, season_path: str, cache: bool) -> list[dict]:
    """Alle Spiele einer Saison: die Saisonseite und jede Spieltags-/Rundenseite aus ihrer Auswahlliste."""
    first = get_text(f"{BASE}/{COMPS[comp]}/{season_path}/spiele-und-ergebnisse", cache=cache)
    links = sorted(set(re.findall(rf'/live-und-ergebnisse/fussball/{COMPS[comp]}/{season_path}/[^"]*?spiele-und-ergebnisse', first)))
    seen: dict[int, dict] = {m["id"]: m for m in parse_list(first)}
    for link in links:
        for m in parse_list(get_text(f"https://www.sportschau.de{link}", cache=cache, delay=0 if cache else DELAY / 2)):
            seen[m["id"]] = m
    return list(seen.values())


def parse_team_stats(page: str) -> tuple[dict, dict]:
    """(Heim, Gast) aus der Teamstatistik: {spalte: wert}."""
    home, away = {}, {}
    for key, li in re.findall(r'<li class="team_stats-([a-z_]+)[^"]*">(.*?)</li>', page, re.S):
        col = TEAM_KEYS.get(key)
        if not col:
            continue
        h = re.search(r'hs-value-home">([^<]*)<', li)
        a = re.search(r'hs-value-away">([^<]*)<', li)
        if h and a:
            home[col], away[col] = _num(h.group(1)), _num(a.group(1))
    return home, away


def parse_players(page: str, column: str) -> list[dict]:
    """Spielertabelle (Laufleistung oder Höchstgeschwindigkeit): Name, Sportschau-Team-ID, Minuten, Wert."""
    out = []
    for team, row in re.findall(r'<tr class="[^"]*entry[^"]*" data-team_id="(\d+)"[^>]*>(.*?)</tr>', page, re.S):
        name = re.search(r'person-name person-name-list"><a[^>]*>([^<]+)<', row)
        mins = re.search(r'person_stats-playing_minutes[^"]*">([^<]*)<', row)
        val = re.search(rf'person_stats-{column}[^"]*">([^<]*)<', row)
        if name and val:
            out.append({"player": htmllib.unescape(name.group(1)).strip(), "team": team,
                        "minutes": int(_num(mins.group(1)) or 0) if mins else None, "value": _num(val.group(1))})
    return out


def _sim(ours: str, theirs: list[str]) -> float:
    a = _norm(ours)
    return max(difflib.SequenceMatcher(None, a, _norm(t)).ratio() for t in theirs)


def _our_matches(session: Session, comp: str, season: int) -> list[dict]:
    if comp == "BL":
        sql = """SELECT m.id, m.kickoff, ht.name AS home, at.name AS away FROM match m
                 JOIN season s ON s.id = m.season_id JOIN team ht ON ht.id = m.home_team_id
                 JOIN team at ON at.id = m.away_team_id WHERE s.start_year = :s"""
    else:
        sql = """SELECT m.id, m.kickoff, ht.name AS home, at.name AS away FROM eu_match m
                 JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
                 WHERE m.competition = :c AND m.season = :s"""
    return [dict(r._mapping) for r in session.execute(text(sql), {"c": comp, "s": season})]


def match_up(ours: list[dict], theirs: list[dict]) -> dict[int, dict]:
    """Unsere Spiel-ID → Sportschau-Spiel: Anstoß ±36 Stunden, höchste Namensähnlichkeit, jedes nur einmal."""
    pairs = []
    for o in ours:
        for t in theirs:
            if abs(o["kickoff"] - t["kickoff"]) <= timedelta(hours=36):
                score = _sim(o["home"], t["home"]) + _sim(o["away"], t["away"])
                if score >= MIN_SCORE:
                    pairs.append((score, o["id"], t["id"], t))
    out, used = {}, set()
    for score, oid, tid, t in sorted(pairs, key=lambda p: -p[0]):
        if oid not in out and tid not in used:
            out[oid] = t
            used.add(tid)
    return out


def _fetch(comp: str, match_id: int, m: dict, now: datetime) -> tuple[list[dict], list[dict]]:
    url = f"https://www.sportschau.de{m['path']}"
    home, away = parse_team_stats(get_text(f"{url}/spiel-team-statistik", cache=True, delay=DELAY))
    teams = []
    for is_home, vals in ((True, home), (False, away)):
        teams.append({"competition": comp, "match_id": match_id, "is_home": is_home, "sportschau_id": m["id"],
                      **{c: vals.get(c) for c in TEAM_KEYS.values()}, "fetched_at": now})
    players: dict[tuple, dict] = {}
    if comp in PLAYER_COMPS and home.get("distance_km") is not None:
        for page, col, field in (("spiel-statistik-laufleistung", "tracking_distance", "distance_km"),
                                 ("spiel-statistik-laufleistung-topspeed", "tracking_max_speed", "top_speed")):
            for p in parse_players(get_text(f"{url}/{page}", cache=True, delay=DELAY), col):
                is_home = p["team"] == m["home_team"] if m["home_team"] else None
                if is_home is None:
                    continue
                row = players.setdefault((is_home, p["player"]), {
                    "competition": comp, "match_id": match_id, "is_home": is_home, "player": p["player"]})
                row[field] = p["value"]
                if p["minutes"] is not None:
                    row["minutes"] = p["minutes"]
    return teams, list(players.values())


def ingest(session: Session, comps=tuple(COMPS), season_years: list[int] | None = None, log=print) -> dict:
    """Ohne season_years nur die laufende Saison je Wettbewerb (für das regelmäßige Update)."""
    now = datetime.now(timezone.utc)
    result = {}
    for comp in comps:
        available = seasons(comp)
        years = season_years or [max(available)]
        done = {r[0] for r in session.execute(text(
            "SELECT DISTINCT match_id FROM match_extra_stats WHERE competition = :c"), {"c": comp})}
        n = 0
        for year in sorted(y for y in years if y in available and y >= FIRST_SEASON[comp]):
            theirs = season_matches(comp, available[year], cache=year < max(available))
            mapped = match_up(_our_matches(session, comp, year), theirs)
            todo = [(mid, m) for mid, m in mapped.items()
                    if mid not in done and m["finished"] and m["kickoff"] < now - AFTER]
            log(f"  {comp} {year}: {len(theirs)} Spiele bei der Sportschau, {len(mapped)} zugeordnet, {len(todo)} neu")
            for i, (mid, m) in enumerate(todo, 1):
                try:
                    teams, players = _fetch(comp, mid, m, now)
                except Exception as exc:  # einzelne Seite nicht erreichbar: beim nächsten Lauf wieder
                    log(f"    {m['path']}: {exc}")
                    continue
                upsert(session, MatchExtraStats, teams, ["competition", "match_id", "is_home"])
                upsert(session, PlayerTracking, players, ["competition", "match_id", "is_home", "player"])
                if comp == "BL":  # Ballbesitz auch in der Spielstatistik (vorher ohne Quelle)
                    session.execute(text("""
                        UPDATE match_team_stats s SET possession = e.possession FROM match_extra_stats e
                        WHERE e.competition = 'BL' AND e.match_id = :m AND s.match_id = e.match_id
                          AND s.is_home = e.is_home AND e.possession IS NOT NULL"""), {"m": mid})
                n += 1
                if i % 50 == 0:
                    session.commit()
                    log(f"    {i}/{len(todo)}")
            session.commit()
        result[comp] = n
    return result


def for_match(competition: str, match_id: int) -> dict | None:
    """Teamwerte und Spieler-Laufdaten eines Spiels für die Detailseite (None ohne Werte)."""
    from fussballdb.db.session import SessionLocal

    with SessionLocal() as s:
        rows = {r.is_home: dict(r._mapping) for r in s.execute(text(
            f"""SELECT is_home, {', '.join(TEAM_KEYS.values())} FROM match_extra_stats
                WHERE competition = :c AND match_id = :m"""), {"c": competition, "m": match_id})}
        if len(rows) != 2 or all(v is None for r in rows.values() for k, v in r.items() if k != "is_home"):
            return None
        players = [dict(r._mapping) for r in s.execute(text(
            """SELECT is_home, player, minutes, distance_km, top_speed FROM player_tracking
               WHERE competition = :c AND match_id = :m ORDER BY distance_km DESC NULLS LAST"""),
            {"c": competition, "m": match_id})]
    strip = lambda r: {k: v for k, v in r.items() if k != "is_home"}  # noqa: E731
    return {"home": strip(rows[True]), "away": strip(rows[False]),
            "spieler": {"home": [strip(p) for p in players if p["is_home"]],
                        "away": [strip(p) for p in players if not p["is_home"]]}}
