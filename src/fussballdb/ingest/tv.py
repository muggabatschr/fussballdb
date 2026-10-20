"""TV-Sender der Bundesliga- und Champions-League-Spiele in Deutschland und Österreich.

Quelle ist das TV-Programm von FotMob (je Land eine Seite, die nächsten 7 Tage). Die Spiele werden über
Anstoßzeit und Teamnamen unseren Spielen zugeordnet. Einträge bleiben nach dem Spiel gespeichert.
"""

import difflib
import json
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.models import TvListing
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.europe import _norm
from fussballdb.ingest.http import get_text
from fussballdb.ingest.upsert import upsert

URL = "https://www.fotmob.com/de/tv-guide/{country}"
COUNTRIES = ("de", "at")
LEAGUES = {54: "BL", 42: "CL"}  # FotMob-Wettbewerb -> unsere Kennung

# Sendernamen für die Anzeige zusammenfassen (Reihenfolge der Regeln zählt)
SIMPLIFY = [
    (r"^Sky Go$", None),  # Streaming-Zugang zu Sky, kein eigener Sender
    (r"zu bestätigen|^TBC", None),
    (r"^Sky", "Sky"),  # alle Sky-Kanäle (Bundesliga 1–5, Top Event, Sky X, Sky Stream …); in AT = Sky Austria
    (r"^DAZN", "DAZN"),
    (r"(Amazon )?Prime Video", "Prime Video"),
    (r"^Canal\+", "Canal+"),
    (r"^ServusTV", "ServusTV"),
    (r"^Puls ?24|^PULS 4|^Puls 4", "Puls 4"),
    (r"^ORF", "ORF"),
    (r"^Sat\.? ?1", "Sat.1"),
    (r"^RTL", "RTL"),
    (r"^ZDF", "ZDF"),
    (r"^ARD|^Das Erste", "ARD"),
]


def simplify(channels: list[str], country: str = "DE") -> list[str]:
    """Sender für die Anzeige: Kanäle desselben Anbieters zusammengefasst, Sky in Österreich als Sky Austria."""
    out = []
    for name in channels:
        short = name
        for pattern, repl in SIMPLIFY:
            if re.search(pattern, name):
                short = repl
                break
        if short == "Sky" and country.upper() == "AT":
            short = "Sky Austria"
        if short and short not in out:
            out.append(short)
    return sorted(out, key=lambda n: n == "WOW")  # WOW (Sky-Streaming) hinter die Sender


def for_matches(competition: str, match_ids: list[int]) -> dict[int, dict[str, list[str]]]:
    """Match-ID -> {"DE": [...], "AT": [...]} mit zusammengefassten Sendern (für API und Web)."""
    from fussballdb.db.session import engine

    if not match_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT match_id, country, channels FROM tv_listing WHERE competition = :c "
                                 "AND match_id = ANY(:ids)"), {"c": competition, "ids": list(match_ids)}).all()
    out: dict[int, dict[str, list[str]]] = {}
    for match_id, country, channels in rows:
        raw = json.loads(channels)
        names = simplify(raw, country) or (["noch offen"] if raw else [])  # z. B. "Noch zu bestätigen"
        if names:
            out.setdefault(match_id, {})[country] = names
    return out


def _listings(country: str) -> list[dict]:
    html = get_text(URL.format(country=country), headers=BROWSER_HEADERS)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("FotMob-TV-Programm: Seitenaufbau hat sich geändert (__NEXT_DATA__ fehlt)")
    fallback = json.loads(m.group(1))["props"]["pageProps"]["fallback"]
    groups = next((v for k, v in fallback.items() if k.startswith("tvguide-groups")), {})
    out = []
    for leagues in groups.values():
        for league in leagues:
            comp = LEAGUES.get(league.get("leagueId"))
            if not comp:
                continue
            for match in league.get("matches", []):
                out.append({"competition": comp,
                            "kickoff": datetime.fromisoformat(match["utcTime"].replace("Z", "+00:00")),
                            "home": match["home"]["name"], "away": match["away"]["name"],
                            "channels": [c["name"] for c in match.get("channels", [])]})
    return out


def _candidates(session: Session) -> dict[str, list[tuple]]:
    """Offene und kürzlich gespielte Spiele je Wettbewerb: (id, Anstoß, Heimname(n), Gastname(n))."""
    bl = session.execute(text("""
        SELECT m.id, m.kickoff,
               string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
        FROM match m JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
        LEFT JOIN team_alias ha ON ha.team_id = ht.id LEFT JOIN team_alias aa ON aa.team_id = at.id
        WHERE m.kickoff BETWEEN now() - interval '2 days' AND now() + interval '10 days'
        GROUP BY m.id, m.kickoff, ht.name, at.name""")).all()
    cl = session.execute(text("""
        SELECT m.id, m.kickoff,
               string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
        FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
        LEFT JOIN eu_team_alias ha ON ha.team_id = ht.id LEFT JOIN eu_team_alias aa ON aa.team_id = at.id
        WHERE m.competition = 'CL' AND m.kickoff BETWEEN now() - interval '2 days' AND now() + interval '10 days'
        GROUP BY m.id, m.kickoff, ht.name, at.name""")).all()
    return {"BL": bl, "CL": cl}


def _similarity(name: str, aliases: str) -> float:
    target = _norm(name)
    return max((difflib.SequenceMatcher(None, target, _norm(a)).ratio() for a in aliases.split("|") if a), default=0.0)


def ingest(session: Session) -> dict:
    """TV-Sender laden und zuordnen. Liefert Anzahl zugeordneter Einträge und nicht zuordenbare Spiele."""
    candidates = _candidates(session)
    rows, unmatched = [], []
    for country in COUNTRIES:
        for item in _listings(country):
            same_time = [c for c in candidates[item["competition"]] if c[1] == item["kickoff"]]
            scored = [(_similarity(item["home"], c[2]) + _similarity(item["away"], c[3]), c) for c in same_time]
            best = max(scored, default=None, key=lambda x: x[0])
            if best is None or best[0] < 1.0:  # beide Namen müssen halbwegs passen
                unmatched.append(f"{item['competition']} {item['home']} – {item['away']}")
                continue
            rows.append({"competition": item["competition"], "match_id": best[1][0], "country": country.upper(),
                         "channels": json.dumps(item["channels"], ensure_ascii=False), "fetched_at": datetime.now().astimezone()})
    upsert(session, TvListing, rows, ["competition", "match_id", "country"])
    return {"zugeordnet": len(rows), "nicht_zugeordnet": sorted(set(unmatched))}
