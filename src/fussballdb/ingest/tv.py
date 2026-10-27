"""TV-Sender der Spiele von Bundesliga, 2. Bundesliga, DFB-Pokal und Champions League in Deutschland und
Österreich.

Quelle ist das TV-Programm von FotMob (je Land eine Seite, die nächsten 7 Tage). Die Spiele werden über
Anstoßzeit und Teamnamen unseren Spielen zugeordnet. Einträge bleiben nach dem Spiel gespeichert.

Die Nummer des Sky-Bundesliga-Kanals ist bei FotMob für Deutschland oft falsch (Leipzig – Elversberg
2026/27: DE 2, AT und LiveOnSat 4). Deshalb kommt für die Bundesliga LiveOnSat als zweite Quelle dazu
(gespeichert als Land "LS"); dessen Kanalnummer gilt in der Anzeige für Deutschland und Österreich.
"""

import difflib
import html
import json
import re
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.models import TvListing
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.europe import _norm
from fussballdb.ingest.http import get_text
from fussballdb.ingest.upsert import upsert

URL = "https://www.fotmob.com/de/tv-guide/{country}"
COUNTRIES = ("de", "at")
LEAGUES = {54: "BL", 42: "CL", 146: "D2", 209: "DFB"}  # FotMob-Wettbewerb -> unsere Kennung
LIVEONSAT_URL = "https://liveonsat.com/europe-germany-bundesliga1.php"
# Kanäle bei LiveOnSat, die für Deutschland und Österreich zählen (die Seite listet Sender aus aller Welt)
LIVEONSAT_KEEP = re.compile(r"^(Sky Sport Bundesliga|Sky Sport Top Event|DAZN Deutsch|WOW)")

# Kanäle, die nur Zugänge oder Kopien sind (Streaming-Zugänge, UHD, Showcase) und "noch offen"
SKIP = re.compile(r"^Sky Go$|^Sky Stream$|^Sky X$|Showcase|UHD|zu bestätigen|^TBC", re.I)
RENAME = [(r"^DAZN.*", "DAZN"), (r"^(Amazon )?Prime Video.*", "Prime Video"), (r"^Canal\+.*", "Canal+")]
NUMBERED_SKY = re.compile(r"^Sky .*\d+( \(Konferenz\))?$")  # Sky Bundesliga 3, Sky Sport Austria 1, Sky Sport 1 (Konferenz)


def channels(raw: list[str]) -> list[str]:
    """Genaue Kanäle für die Anzeige: ohne Zugänge und Kopien. Gibt es einen nummerierten Sky-Kanal, fallen
    der allgemeine Kanal (Sky Bundesliga) und die Top-Event-Kopie weg. WOW (Sky-Streaming) ans Ende."""
    names = [n for n in raw if not SKIP.search(n)]
    if any(NUMBERED_SKY.match(n) for n in names):
        names = [n for n in names if not n.startswith("Sky") or NUMBERED_SKY.match(n)]
    out = []
    for name in names:
        for pattern, repl in RENAME:
            name = re.sub(pattern, repl, name)
        if name not in out:
            out.append(name)
    return sorted(out, key=lambda n: n == "WOW")


SKY_BL = re.compile(r"^Sky (?:Sport )?Bundesliga (\d+)$")  # Sky Bundesliga 4 (DE), Sky Sport Bundesliga 4 (AT)


def _with_numbers(names: list[str], nums: list[str], style: str) -> list[str]:
    """Nummerierte Sky-Bundesliga-Kanäle durch `nums` ersetzen (style: Name mit {n})."""
    if not any(SKY_BL.match(n) for n in names):
        return names
    return [style.format(n=x) for x in nums] + [n for n in names if not SKY_BL.match(n)]


def align_sky_numbers(tv: dict[str, list[str]]) -> dict[str, list[str]]:
    """Sky Österreich zeigt die Bundesliga auf denselben Sky-Bundesliga-Kanälen wie Sky Deutschland, also gilt
    für beide Länder dieselbe Kanalnummer: die von LiveOnSat ("LS"), sonst die österreichische von FotMob
    (stimmte 2026/27 jedes Mal mit LiveOnSat überein, die deutsche nicht). "LS" selbst wird nicht angezeigt."""
    tv = dict(tv)
    ls = tv.pop("LS", [])
    nums = [m.group(1) for n in ls if (m := SKY_BL.match(n))]
    nums = nums or [m.group(1) for n in tv.get("AT", []) if (m := SKY_BL.match(n))]
    if not nums:
        return tv
    for country, style in (("DE", "Sky Bundesliga {n}"), ("AT", "Sky Sport Bundesliga {n}")):
        if country in tv:
            tv[country] = _with_numbers(tv[country], nums, style)
    return tv


def for_matches(competition: str, match_ids: list[int]) -> dict[int, dict[str, list[str]]]:
    """Match-ID -> {"DE": [...], "AT": [...]} mit den Kanälen für die Anzeige (API und Web)."""
    from fussballdb.db.session import engine

    if not match_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT match_id, country, channels FROM tv_listing WHERE competition = :c "
                                 "AND match_id = ANY(:ids)"), {"c": competition, "ids": list(match_ids)}).all()
    out: dict[int, dict[str, list[str]]] = {}
    for match_id, country, raw_json in rows:
        raw = json.loads(raw_json)
        names = channels(raw) or (["noch offen"] if raw else [])  # z. B. "Noch zu bestätigen"
        if names:
            out.setdefault(match_id, {})[country] = names
    return {match_id: tv for match_id, tv in ((m, align_sky_numbers(v)) for m, v in out.items()) if tv}


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


def _liveonsat() -> list[dict]:
    """Bundesliga-Spiele mit den Kanälen für Deutschland und Österreich laut LiveOnSat (nächste Spieltage)."""
    page = get_text(LIVEONSAT_URL, headers=BROWSER_HEADERS)
    out = []
    for block in re.split(r"German 1\. Bundesliga - Week \d+", page)[1:]:
        teams = re.search(r"\n\s*([^<\n]+?) v ([^<\n]+?)\s*\n", re.sub(r"<[^>]+>", "\n", block))
        captions = re.findall(r"CAPTION, '([^']+?) &nbsp;&ndash;&nbsp;(\d{4}-\d\d-\d\d \d\d:\d\d):\d\d'", block)
        if not teams or not captions:
            continue
        names = []
        for raw, _ in captions:
            name = re.sub(r"\s+(HD|UHD|HD max)$", "", html.unescape(raw).strip())
            if LIVEONSAT_KEEP.match(name) and name not in names:
                names.append(name)
        out.append({"competition": "BL", "home": teams.group(1).strip(), "away": teams.group(2).strip(),
                    "kickoff": datetime.fromisoformat(captions[0][1]).replace(tzinfo=timezone.utc),  # Angaben in UTC
                    "channels": names})
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
    out = {"BL": bl}
    for comp in ("CL", "D2", "DFB"):
        out[comp] = session.execute(text("""
            SELECT m.id, m.kickoff,
                   string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
            FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
            LEFT JOIN eu_team_alias ha ON ha.team_id = ht.id LEFT JOIN eu_team_alias aa ON aa.team_id = at.id
            WHERE m.competition = :c AND m.kickoff BETWEEN now() - interval '2 days' AND now() + interval '10 days'
            GROUP BY m.id, m.kickoff, ht.name, at.name"""), {"c": comp}).all()
    return out


CONFERENCE_MIN = 3  # ab so vielen Spielen zur selben Zeit kann ein gemeinsamer Kanal eine Konferenz sein
SKY_NUMBERED = re.compile(r"^Sky Sport \d+$")


def mark_conference(items: list[dict]) -> list[dict]:
    """Ein nummerierter Sky-Kanal, der bei allen Spielen eines Wettbewerbs zur selben Anstoßzeit steht, ist die
    Konferenz (Pokal: in Österreich Sky Sport 1 bei jedem Spiel) und heißt dann "Sky Sport 1 (Konferenz)"."""
    slots: dict[tuple, list[dict]] = {}
    for it in items:
        slots.setdefault((it["competition"], it["kickoff"]), []).append(it)
    for games in slots.values():
        if len(games) < CONFERENCE_MIN:
            continue
        common = set.intersection(*(set(g["channels"]) for g in games))
        for ch in (c for c in common if SKY_NUMBERED.match(c)):
            for g in games:
                g["channels"] = [f"{c} (Konferenz)" if c == ch else c for c in g["channels"]]
    return items


def conference_to_de(rows: list[dict]) -> list[dict]:
    """FotMob nennt die Sky-Konferenz nur für Österreich. Sky Deutschland zeigt sie auf demselben Kanal (Pokal
    2026/27: Sky Sport 1, laut Sky und den Vereinen), die Einzelspiel-Kanäle sind ohnehin gleich. Läuft das Spiel
    in Deutschland bei Sky, kommt die österreichische Konferenz deshalb auch in die deutsche Liste."""
    at = {(r["competition"], r["match_id"]): json.loads(r["channels"]) for r in rows if r["country"] == "AT"}
    for r in rows:
        if r["country"] != "DE":
            continue
        de = json.loads(r["channels"])
        conf = [c for c in at.get((r["competition"], r["match_id"]), []) if c.endswith("(Konferenz)")]
        if conf and any(c.startswith("Sky Sport") for c in de) and not any(c.endswith("(Konferenz)") for c in de):
            r["channels"] = json.dumps(conf + de, ensure_ascii=False)
    return rows


def _similarity(name: str, aliases: str) -> float:
    target = _norm(name)
    return max((difflib.SequenceMatcher(None, target, _norm(a)).ratio() for a in aliases.split("|") if a), default=0.0)


def ingest(session: Session) -> dict:
    """TV-Sender laden und zuordnen. Liefert Anzahl zugeordneter Einträge und nicht zuordenbare Spiele."""
    candidates = _candidates(session)
    rows, unmatched = [], []
    sources = [(c.upper(), lambda c=c: _listings(c)) for c in COUNTRIES] + [("LS", _liveonsat)]
    for country, load in sources:
        try:
            items = load()
        except Exception as exc:  # LiveOnSat ist nur Ergänzung: fällt es aus, bleibt FotMob
            if country != "LS":
                raise
            unmatched.append(f"LiveOnSat nicht erreichbar: {exc}")
            continue
        for item in mark_conference(items):
            same_time = [c for c in candidates[item["competition"]] if c[1] == item["kickoff"]]
            if not same_time and country == "LS":
                continue  # LiveOnSat listet auch Spieltage weiter in der Zukunft
            scored = [(_similarity(item["home"], c[2]) + _similarity(item["away"], c[3]), c) for c in same_time]
            best = max(scored, default=None, key=lambda x: x[0])
            if best is None or best[0] < 1.0:  # beide Namen müssen halbwegs passen
                unmatched.append(f"{item['competition']} {item['home']} – {item['away']}")
                continue
            rows.append({"competition": item["competition"], "match_id": best[1][0], "country": country,
                         "channels": json.dumps(item["channels"], ensure_ascii=False), "fetched_at": datetime.now().astimezone()})
    upsert(session, TvListing, conference_to_de(rows), ["competition", "match_id", "country"])
    return {"zugeordnet": len(rows), "nicht_zugeordnet": sorted(set(unmatched))}
