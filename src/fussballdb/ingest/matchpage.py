"""Aufstellung und Momentum je Spiel von der FotMob-Spielseite (Bundesliga, 2. Bundesliga, DFB-Pokal, CL).

Aufstellung: Formation, Teamnote, Trainer, Startelf mit Position auf dem Feld (FotMob-Layout, waagerecht und
senkrecht), Rückennummer, Note, Spieler des Spiels, Kapitän, Tore, Vorlagen, Karten, Auswechslung; dazu die
Bank mit Einwechselminute. Vor dem Spiel ist es die voraussichtliche Aufstellung (lineup_type "predicted"),
etwa eine Stunde vor dem Anpfiff die offizielle.

Momentum: FotMobs Kurve je Minute von -100 bis 100 (> 0 = Heimteam drückt), dazu Tore und Platzverweise als
Marken auf der Zeitachse.

Teamfarben: FotMob wählt sie je Spiel so, dass sich Heim und Gast unterscheiden, für hellen und dunklen Modus
mit passender Schriftfarbe. Ohne Spielseite (Spiele weiter in der Zukunft) gilt die Stammfarbe des Teams, die
Farbe, die es bei FotMob am häufigsten als Heimteam hatte (team_colors).

Die FotMob-ID kommt aus match_venue (Stadien, laufende Saison); backfill() ordnet ältere Bundesliga-Saisons
über den FotMob-Spielplan zu."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.models import MatchPage
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.cl_xg import MATCH, _next_data
from fussballdb.ingest.http import get_text
from fussballdb.ingest.upsert import upsert
from fussballdb.ingest import venues

BEFORE = timedelta(days=2)  # offene Spiele so weit im Voraus (voraussichtliche Aufstellung)
CARD = {"Yellow": "gelb", "Red": "rot", "YellowRed": "gelbrot"}


def _player(p: dict) -> dict:
    perf = p.get("performance") or {}
    events = [e.get("type") for e in perf.get("events") or []]
    subs = {e.get("type"): e.get("time") for e in perf.get("substitutionEvents") or []}
    h, v = p.get("horizontalLayout") or {}, p.get("verticalLayout") or {}
    out = {"name": p.get("lastName") or p.get("name"), "voller_name": p.get("name"),
           "nummer": p.get("shirtNumber"), "note": perf.get("rating"),
           "tore": events.count("goal"), "vorlagen": events.count("assist"), "eigentore": events.count("ownGoal"),
           "gelb": "yellowCard" in events, "rot": "redCard" in events,
           "elfmeter_verschossen": events.count("missedPenalty"), "elfmeter_gehalten": events.count("savedPenalty"),
           "raus": subs.get("subOut"), "rein": subs.get("subIn")}
    if perf.get("playerOfTheMatch"):
        out["spieler_des_spiels"] = True
    if p.get("isCaptain"):
        out["kapitaen"] = True
    if h:
        out["x"], out["y"] = h.get("x"), h.get("y")  # waagerecht: x 0 = eigenes Tor, 1 = Mittellinie
    if v:
        out["vx"], out["vy"] = v.get("x"), v.get("y")  # senkrecht: vy 0 = eigenes Tor
    return out


def _team(t: dict) -> dict:
    coach = t.get("coach") or {}
    return {"name": t.get("name"), "formation": t.get("formation"), "note": t.get("rating"),
            "trainer": coach.get("name"),
            "startelf": [_player(p) for p in t.get("starters") or []],
            "bank": [_player(p) for p in t.get("subs") or []]}


def parse(page: dict) -> dict:
    """Aufstellung, Momentum und Ereignisse aus den Daten einer FotMob-Spielseite (__NEXT_DATA__)."""
    content = page.get("content") or {}
    lu = content.get("lineup") or {}
    lineup = ({"home": _team(lu["homeTeam"]), "away": _team(lu["awayTeam"])}
              if lu.get("homeTeam") and lu["homeTeam"].get("starters") else None)
    mo = (content.get("momentum") or (content.get("matchFacts") or {}).get("momentum") or {})
    mo = (mo.get("main") or mo).get("data") if isinstance(mo, dict) else None
    momentum = [[d["minute"], d["value"]] for d in mo or [] if d.get("minute") is not None]
    events = []
    for e in ((content.get("matchFacts") or {}).get("events") or {}).get("events") or []:
        minute = (e.get("time") or 0) + (e.get("overloadTime") or 0) / 10  # 45+3 -> 45,3 (nur für die Lage)
        name = e.get("nameStr") or (e.get("player") or {}).get("name")
        if e.get("type") == "Goal":
            events.append({"minute": e.get("time"), "nachspiel": e.get("overloadTime") or None, "pos": minute,
                           "heim": e.get("isHome"), "art": "eigentor" if e.get("ownGoal") else "tor", "spieler": name,
                           "stand": e.get("newScore")})
        elif e.get("type") == "Card" and e.get("card") in ("Red", "YellowRed"):
            events.append({"minute": e.get("time"), "nachspiel": e.get("overloadTime") or None, "pos": minute,
                           "heim": e.get("isHome"), "art": CARD[e["card"]], "spieler": name})
        elif e.get("type") == "MissedPenalty":
            events.append({"minute": e.get("time"), "nachspiel": e.get("overloadTime") or None, "pos": minute,
                           "heim": e.get("isHome"), "art": "elfmeter_vergeben", "spieler": name})
    tc = (page.get("general") or {}).get("teamColors") or {}
    colors = ({"hell": tc.get("lightMode"), "dunkel": tc.get("darkMode"),
               "schrift_hell": tc.get("fontLightMode"), "schrift_dunkel": tc.get("fontDarkMode")}
              if tc.get("lightMode") else None)
    return {"lineup_type": lu.get("lineupType"), "lineup": lineup, "momentum": momentum or None, "events": events,
            "colors": colors}


def _fetch(comp: str, match_id: int, fotmob_id: int, finished: bool, now: datetime) -> dict | None:
    try:
        page = _next_data(get_text(MATCH.format(id=fotmob_id), headers=BROWSER_HEADERS, cache=finished, delay=1.0))
    except Exception:  # einzelne Seite nicht erreichbar: beim nächsten Lauf wieder
        return None
    p = parse(page)
    return {"competition": comp, "match_id": match_id, "fotmob_id": fotmob_id, "lineup_type": p["lineup_type"],
            "lineup": json.dumps(p["lineup"], ensure_ascii=False) if p["lineup"] else None,
            "momentum": json.dumps(p["momentum"]) if p["momentum"] else None,
            "events": json.dumps(p["events"], ensure_ascii=False),
            "colors": json.dumps(p["colors"]) if p["colors"] else None, "frozen": finished, "fetched_at": now}


def ingest(session: Session, log=print) -> int:
    """Spiele mit FotMob-ID (aus match_venue): gespielte einmal (dann eingefroren), offene der nächsten zwei Tage
    neu, sobald der letzte Abruf älter als eine Stunde ist."""
    now = datetime.now(timezone.utc)
    todo = session.execute(text("""
        WITH games AS (
            SELECT 'BL' AS c, id, kickoff, finished FROM match
            UNION ALL SELECT competition, id, kickoff, finished FROM eu_match)
        SELECT v.competition, v.match_id, v.fotmob_id, g.finished FROM match_venue v
        JOIN games g ON g.c = v.competition AND g.id = v.match_id
        LEFT JOIN match_page p ON p.competition = v.competition AND p.match_id = v.match_id
        WHERE v.fotmob_id IS NOT NULL AND (p.id IS NULL OR NOT p.frozen)
          AND (g.finished OR g.kickoff < :soon)
          AND (p.id IS NULL OR g.finished OR p.fetched_at < :stale)"""),
        {"soon": now + BEFORE, "stale": now - timedelta(hours=1)}).all()
    rows = [r for r in (_fetch(c, m, f, fin, now) for c, m, f, fin in todo) if r]
    upsert(session, MatchPage, rows, ["competition", "match_id"])
    return len(rows)


def backfill(session: Session, season: int, log=print) -> dict:
    """Ältere Bundesliga-Saison: FotMob-Spielplan zuordnen und alle gespielten Spiele laden (~1 s je Spiel)."""
    now = datetime.now(timezone.utc)
    cands = session.execute(text("""
        SELECT m.id, m.kickoff, m.finished,
               string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
        FROM match m JOIN season s ON s.id = m.season_id
        JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
        LEFT JOIN team_alias ha ON ha.team_id = ht.id LEFT JOIN team_alias aa ON aa.team_id = at.id
        WHERE s.start_year = :y AND m.finished
          AND NOT EXISTS (SELECT 1 FROM match_page p WHERE p.competition = 'BL' AND p.match_id = m.id AND p.frozen)
        GROUP BY m.id, m.kickoff, m.finished, ht.name, at.name"""), {"y": season}).all()
    rows, unmatched = [], []
    for fx in venues._fixtures("BL", season):
        best = venues.pair(fx, cands)
        if best is False:
            unmatched.append(f"{fx['home']} – {fx['away']}")
        if not best:
            continue
        cands = [c for c in cands if c[0] != best[0]]
        if (row := _fetch("BL", best[0], fx["id"], True, now)):
            rows.append(row)
            if len(rows) % 50 == 0:
                log(f"  {len(rows)} Spiele")
                upsert(session, MatchPage, rows[-50:], ["competition", "match_id"])
                session.commit()
    upsert(session, MatchPage, rows, ["competition", "match_id"])
    return {"spiele": len(rows), "nicht_zugeordnet": unmatched}


def reparse(session: Session, log=print) -> int:
    """Alle gespeicherten Spiele neu auswerten (nach einer Erweiterung von parse); gespielte Spiele kommen aus dem
    Zwischenspeicher, es geht nichts übers Netz."""
    now = datetime.now(timezone.utc)
    todo = session.execute(text("SELECT competition, match_id, fotmob_id, frozen FROM match_page WHERE frozen")).all()
    rows = [r for r in (_fetch(c, m, f, True, now) for c, m, f, _ in todo) if r]
    upsert(session, MatchPage, rows, ["competition", "match_id"])
    return len(rows)


SURFACE = {"hell": "#ffffff", "dunkel": "#1b1b19"}  # Kartenhintergrund der Web-App
MIN_DISTANCE = 110  # Abstand im RGB-Raum, ab dem Heim und Gast klar unterscheidbar sind
MIN_CONTRAST = 1.6  # Kontrast zum Hintergrund, damit Balken und Kreise sichtbar sind


def _rgb(c: str) -> tuple[int, int, int] | None:
    c = (c or "").strip()
    if c.startswith("#") and len(c) in (4, 7):
        c = "".join(ch * 2 for ch in c[1:]) if len(c) == 4 else c[1:]
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return None


def _lum(c: str) -> float:
    def ch(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(c) or (128, 128, 128)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _distance(a: str, b: str) -> float:
    ra, rb = _rgb(a), _rgb(b)
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5 if ra and rb else 0.0


def _font(c: str) -> str:
    return "rgba(255, 255, 255, 1.0)" if _contrast(c, "#ffffff") >= _contrast(c, "#1d1d1d") else "rgba(29, 29, 29, 1.0)"


def team_palettes() -> dict[str, list[str]]:
    """Alle Farben, die FotMob einem Team gegeben hat (als Heim- und Gastteam, hell und dunkel), die häufigste
    zuerst. Die erste ist die Stammfarbe, die weiteren dienen als Zweitfarbe, wenn sie sich mit dem Gegner beißt."""
    from collections import Counter

    from fussballdb.db.session import engine

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT coalesce(th.name, eh.name) AS home, coalesce(ta.name, ea.name) AS away, p.colors FROM match_page p
            LEFT JOIN match m ON p.competition = 'BL' AND m.id = p.match_id
            LEFT JOIN team th ON th.id = m.home_team_id LEFT JOIN team ta ON ta.id = m.away_team_id
            LEFT JOIN eu_match em ON p.competition <> 'BL' AND em.id = p.match_id
            LEFT JOIN eu_team eh ON eh.id = em.home_id LEFT JOIN eu_team ea ON ea.id = em.away_id
            WHERE p.colors IS NOT NULL""")).all()
    seen: dict[str, Counter] = {}
    for home, away, raw in rows:
        c = json.loads(raw)
        for team, side in ((home, "home"), (away, "away")):
            for mode in ("hell", "dunkel"):
                col = ((c.get(mode) or {}).get(side) or "").lower()
                if _rgb(col):
                    seen.setdefault(team, Counter())[col] += 2 if side == "home" else 1
    return {team: [col for col, _ in cnt.most_common()] for team, cnt in seen.items()}


def team_colors() -> dict[str, dict]:
    """Stammfarbe je Team (unser Teamname) für hellen und dunklen Modus, mit passender Schrift."""
    out = {}
    for team, pal in team_palettes().items():
        mode_color = {m: next((c for c in pal if _contrast(c, SURFACE[m]) >= MIN_CONTRAST), pal[0]) for m in SURFACE}
        out[team] = {"hell": mode_color["hell"], "dunkel": mode_color["dunkel"],
                     "schrift_hell": _font(mode_color["hell"]), "schrift_dunkel": _font(mode_color["dunkel"])}
    return out


def _pick(home: list[str], away: list[str], surface: str) -> tuple[str | None, str | None]:
    """Farbpaar für einen Modus: so wenig Änderungen wie möglich (je Team die erste Farbe der Liste ist die
    vorgesehene), Heim und Gast klar verschieden und beide gut sichtbar auf dem Hintergrund. Muss eins wechseln,
    nimmt das Team seine Zweitfarbe, bei dem das Paar am besten zum Layout passt (höchster Kontrast)."""
    best, best_key = (home[0] if home else None, away[0] if away else None), None
    for i, h in enumerate(home[:6]):
        for j, a in enumerate(away[:6]):
            if _distance(h, a) < MIN_DISTANCE or min(_contrast(h, surface), _contrast(a, surface)) < MIN_CONTRAST:
                continue
            key = ((i > 0) + (j > 0), i + j, -min(_contrast(h, surface), _contrast(a, surface)))
            if best_key is None or key < best_key:
                best, best_key = (h, a), key
    return best


def colors_for(competition: str, match_id: int, home: str, away: str) -> dict | None:
    """Farben für Heim und Gast je Modus: die von der Spielseite, sonst die Stammfarben; beißen sie sich oder
    heben sie sich schlecht vom Hintergrund ab, kommt die Zweitfarbe eines Teams (siehe _pick)."""
    from fussballdb.db.session import engine

    with engine.connect() as conn:
        raw = conn.scalar(text("SELECT colors FROM match_page WHERE competition = :c AND match_id = :m"),
                          {"c": competition, "m": match_id})
    page = json.loads(raw) if raw else {}
    pal = team_palettes()
    out: dict = {"home": {}, "away": {}}
    for mode, surface in SURFACE.items():
        given = page.get(mode) or {}
        cands = {}
        for side, team in (("home", home), ("away", away)):
            first = [c.lower() for c in (given.get(side), (page.get("dunkel" if mode == "hell" else "hell") or {}).get(side)) if _rgb(c or "")]
            cands[side] = list(dict.fromkeys(first + pal.get(team, [])))
        h, a = _pick(cands["home"], cands["away"], surface)
        for side, col in (("home", h), ("away", a)):
            if col:
                out[side][mode] = col
                out[side][f"schrift_{mode}"] = _font(col)
    res = {side: (v if "hell" in v and "dunkel" in v else None) for side, v in out.items()}
    return res if res["home"] or res["away"] else None


def lineup_names(match_ids: list[int]) -> dict[tuple[int, bool], dict]:
    """Bundesliga: (Match-ID, Heim?) -> {"offiziell", "startelf", "bank"} mit normalisierten Namen (voll und
    Nachname) aus der FotMob-Aufstellung, für die Einsatzchancen (features/kickbase_projection.py)."""
    from fussballdb.db.session import engine
    from fussballdb.features.lineup_strength import _norm

    if not match_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT match_id, lineup_type, lineup FROM match_page WHERE competition = 'BL' "
                                 "AND match_id = ANY(:ids) AND lineup IS NOT NULL"), {"ids": list(match_ids)}).all()
    names = lambda ps: {n for p in ps for n in (_norm(p.get("voller_name") or ""), "_last:" + _norm(p.get("name") or ""))}  # noqa: E731
    out = {}
    for r in rows:
        lu = json.loads(r.lineup)
        for side, home in (("home", True), ("away", False)):
            t = lu.get(side) or {}
            out[(r.match_id, home)] = {"offiziell": r.lineup_type != "predicted", "startelf": names(t.get("startelf", [])),
                                       "bank": names(t.get("bank", []))}
    return out


def for_match(competition: str, match_id: int) -> dict | None:
    """Für die Detailseite: {"art", "aufstellung", "momentum", "ereignisse"} oder None."""
    from fussballdb.db.session import engine

    with engine.connect() as conn:
        r = conn.execute(text("SELECT lineup_type, lineup, momentum, events FROM match_page "
                              "WHERE competition = :c AND match_id = :m"), {"c": competition, "m": match_id}).first()
    if not r or not (r.lineup or r.momentum):
        return None
    return {"art": "voraussichtlich" if r.lineup_type == "predicted" else "offiziell",
            "aufstellung": json.loads(r.lineup) if r.lineup else None,
            "momentum": json.loads(r.momentum) if r.momentum else None,
            "ereignisse": json.loads(r.events) if r.events else []}
