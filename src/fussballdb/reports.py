"""Spielberichte: kurzer deutscher Text je Bundesliga-Spiel (ab 2014/15), aus unseren Daten gebaut, nicht von
einem Sprachmodell geschrieben (schnell, rückwirkend für alle Spiele und ohne erfundene Details).

Inhalt: Ergebnis und Halbzeit, jedes Tor mit Minute, Schütze, Vorlage, Art (Elfmeter, Kopfball, Standard …)
und xG (Understat-Schüsse), Joker-Tore, Platzverweise, Statistik (xG, Schüsse, Großchancen, Ecken, PPDA),
Einordnung nach Chancen und nach der Prognose vor dem Spiel, Ausfälle, Stadion und Wetter (ab 2026/27).

Gespeichert in match_report mit Volltextindex (Postgres, Deutsch) und Embedding (pgvector, Modell aus LM Studio)
für die Suche in Chat und MCP (search)."""

import json
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from fussballdb.config import LOCAL_LLM_URL, MODEL_FIRST_SEASON
from fussballdb.db.session import engine

BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
SITUATION = {"Penalty": "Elfmeter", "DirectFreekick": "direkter Freistoß", "FromCorner": "nach Ecke",
             "SetPiece": "nach Standard"}
EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
# nomic-embed erwartet diese Präfixe für Dokumente bzw. Suchanfragen
DOC_PREFIX, QUERY_PREFIX = "search_document: ", "search_query: "


def de(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def _short(name: str) -> str:
    """Nachname für Torschützen ("Harry Kane" -> "Kane"), Einzelnamen bleiben."""
    parts = name.split()
    return " ".join(parts[1:]) if len(parts) > 1 else name


def _goal_lines(m: dict, goals: list[dict], starters: set[str]) -> list[str]:
    h = a = 0
    lines = []
    for g in goals:
        own = g["result"] == "OwnGoal"
        for_home = (g["team_id"] == m["home_id"]) != own  # Eigentor zählt für den Gegner
        h, a = (h + 1, a) if for_home else (h, a + 1)
        details = [f"{g['minute']}."]
        if own:
            details.append("Eigentor")
        else:
            if g["situation"] in SITUATION:
                details.append(SITUATION[g["situation"]])
            if g["shot_type"] == "Head":
                details.append("Kopfball")
            if g["player_assisted"]:
                details.append(f"Vorlage {_short(g['player_assisted'])}")
            if g["player"] not in starters:
                details.append("eingewechselt")
            details.append(f"xG {de(g['xg'], 2)}")
        lines.append(f"{h}:{a} {g['player']} ({', '.join(details)})")
    return lines


def _verdict(m: dict) -> list[str]:
    out = []
    hg, ag, hx, ax = m["home_goals"], m["away_goals"], m["home_xg"], m["away_xg"]
    home, away = m["home_short"], m["away_short"]
    if hx is not None and ax is not None:
        diff = hx - ax
        if hg > ag:
            out.append(f"{home} gewinnt " + ("verdient" if diff >= 0.5 else "glücklich, der Gegner hatte die besseren Chancen"
                                             if diff <= -0.5 else "in einem engen Spiel") + f" (xG {de(hx)} zu {de(ax)}).")
        elif ag > hg:
            out.append(f"{away} gewinnt auswärts " + ("verdient" if diff <= -0.5 else "glücklich, der Gegner hatte die besseren Chancen"
                                                      if diff >= 0.5 else "in einem engen Spiel") + f" (xG {de(hx)} zu {de(ax)}).")
        else:
            out.append("Remis" + (f", obwohl {home if diff > 0 else away} klar die besseren Chancen hatte"
                                  if abs(diff) >= 0.8 else " bei ausgeglichenen Chancen") + f" (xG {de(hx)} zu {de(ax)}).")
    if m["p_home"] is not None:
        winner_p = m["p_home"] if hg > ag else m["p_away"] if ag > hg else m["p_draw"]
        fav = max(("p_home", home), ("p_draw", "ein Remis"), ("p_away", away), key=lambda x: m[x[0]])
        text_fav = f"Vor dem Spiel sah das Modell {fav[1]} vorn ({round(100 * m[fav[0]])} %)"
        if winner_p < 0.25:
            out.append(f"{text_fav}; das Ergebnis war eine Überraschung (nur {round(100 * winner_p)} %).")
        else:
            out.append(f"{text_fav}, das Ergebnis hatte {round(100 * winner_p)} %.")
        if m["tip_home"] is not None:
            out.append(f"Tipp des Modells: {m['tip_home']}:{m['tip_away']}.")
    return out


def _stats_line(s: dict) -> str | None:
    h, a = s.get("home") or {}, s.get("away") or {}
    parts = []
    for key, label, digits in (("xg", "xG", 2), ("shots", "Schüsse", 0), ("shots_on_target", "aufs Tor", 0),
                               ("big_chances", "Großchancen", 0), ("corners", "Ecken", 0), ("ppda", "PPDA", 1)):
        if h.get(key) is not None and a.get(key) is not None:
            parts.append(f"{label} {de(h[key], digits)}:{de(a[key], digits)}" if digits else f"{label} {h[key]}:{a[key]}")
    return "Statistik: " + ", ".join(parts) + "." if parts else None


def _keywords(m: dict, goals: list[dict], starters: set[str], reds: list[dict]) -> list[str]:
    """Stichworte zum Spielverlauf, aus den Daten abgeleitet (helfen der Suche nach Verläufen)."""
    hg, ag = m["home_goals"], m["away_goals"]
    winner = m["home_short"] if hg > ag else m["away_short"] if ag > hg else None
    loser = m["away_short"] if hg > ag else m["home_short"] if ag > hg else None
    words = []
    # Spielstand nach jedem Tor, um Rückstände und späte Entscheidungen zu erkennen
    h = a = 0
    trailed_home = trailed_away = False
    deciding_minute = None
    for g in goals:
        for_home = (g["team_id"] == m["home_id"]) != (g["result"] == "OwnGoal")
        h, a = (h + 1, a) if for_home else (h, a + 1)
        trailed_home |= h < a
        trailed_away |= a < h
        if (h, a) == (hg, ag):
            deciding_minute = g["minute"]
    if hg > ag and trailed_home or ag > hg and trailed_away:
        words.append(f"Comeback von {winner}, {winner} gewinnt nach Rückstand, Spiel gedreht")
    elif hg == ag and (trailed_home or trailed_away) and hg > 0:
        words.append("Aufholjagd, Rückstand ausgeglichen")
    if hg != ag and deciding_minute and deciding_minute >= 85 and abs(hg - ag) == 1:
        words.append(f"spätes Siegtor von {winner}, Last-Minute-Tor")
    elif hg == ag and deciding_minute and deciding_minute >= 85:
        words.append("später Ausgleich in der Schlussphase")
    if hg + ag >= 5:
        words.append("Torfestival, Schützenfest, viele Tore")
    if hg + ag == 0:
        words.append("torlos, Nullnummer")
    elif min(hg, ag) == 0:
        words.append("zu null")
    if abs(hg - ag) >= 3:
        words.append(f"Kantersieg von {winner}, hohe Niederlage von {loser}")
    if reds:
        words.append("Platzverweis, Rote Karte, Unterzahl")
    if any(g["situation"] == "Penalty" for g in goals):
        words.append("Elfmetertor")
    if any(g["result"] == "OwnGoal" for g in goals):
        words.append("Eigentor")
    if any(g["result"] == "Goal" and g["player"] not in starters for g in goals) and starters:
        words.append("Joker-Tor, Tor eines Einwechselspielers")
    if m["home_xg"] is not None and m["away_xg"] is not None and hg != ag:
        diff = (m["home_xg"] - m["away_xg"]) * (1 if hg > ag else -1)
        words.append(f"glücklicher Sieg von {winner}, Sieger mit weniger Chancen" if diff <= -0.5
                     else f"verdienter Sieg von {winner}" if diff >= 0.5 else "knappes Spiel")
    if m["p_home"] is not None:
        winner_p = m["p_home"] if hg > ag else m["p_away"] if ag > hg else m["p_draw"]
        if winner_p < 0.25:
            words.append(f"Überraschung, Außenseiter {winner or 'holt Remis'}")
    if winner:
        words.append(f"{'Auswärtssieg' if ag > hg else 'Heimsieg'} von {winner}, Niederlage von {loser}")
    else:
        words.append("Unentschieden, Remis")
    return words


def build(m: dict, goals: list[dict], starters: set[str], reds: list[dict], stats: dict) -> str:
    """Bericht eines Spiels aus den gesammelten Daten (siehe _load)."""
    kick = m["kickoff"].astimezone(BERLIN)
    venue = f" im {m['stadium']}" if m.get("stadium") else ""
    ht = f" ({m['ht_home']}:{m['ht_away']})" if m["ht_home"] is not None else ""
    lines = [f"Bundesliga {m['season_label']}, {m['matchday']}. Spieltag, {WEEKDAYS[kick.weekday()]} "
             f"{kick:%d.%m.%Y}{venue}: {m['home']} – {m['away']} {m['home_goals']}:{m['away_goals']}{ht}."]
    goal_lines = _goal_lines(m, goals, starters)
    if goal_lines:
        lines.append("Tore: " + "; ".join(goal_lines) + ".")
    elif m["home_goals"] == m["away_goals"] == 0:
        lines.append("Keine Tore.")
    if reds:
        lines.append("Platzverweis: " + ", ".join(f"{r['player']} ({r['team']})" for r in reds) + ".")
    if (st := _stats_line(stats)):
        lines.append(st)
    lines += _verdict(m)
    for side, team in (("missing_home", m["home_short"]), ("missing_away", m["away_short"])):
        if m.get(side):
            lines.append(f"Es fehlten bei {team}: {m[side]}.")
    lines.append("Stichworte: " + "; ".join(_keywords(m, goals, starters, reds)) + ".")
    w = m.get("weather")
    if w and w.get("temp_c") is not None:
        lines.append(f"Wetter: {de(w['temp_c'], 0)} °C" + (f", {de(w['precip_mm'], 1)} mm Regen" if w.get("precip_mm") else "")
                     + (f", Wind {round(w['wind_kmh'])} km/h" if w.get("wind_kmh") is not None else "") + ".")
    return "\n".join(lines)


def _load(where: str, params: dict) -> list[tuple[int, str]]:
    """Alle Daten für die Berichte der ausgewählten Spiele mit wenigen Abfragen laden und Berichte bauen."""
    from fussballdb.ingest.team_mapping import COLLOQUIAL
    from fussballdb.model.ensemble import MODEL_VERSION

    short = lambda n: (COLLOQUIAL.get(n) or [n])[0]  # noqa: E731
    with engine.connect() as conn:
        matches = [dict(r._mapping) for r in conn.execute(text(f"""
            SELECT m.id, m.kickoff, m.matchday, s.start_year AS season, s.label AS season_label,
                   m.home_team_id AS home_id, m.away_team_id AS away_id, ht.name AS home, at.name AS away,
                   m.home_goals, m.away_goals, m.ht_home_goals AS ht_home, m.ht_away_goals AS ht_away,
                   hs.xg AS home_xg, as_.xg AS away_xg, p.p_home, p.p_draw, p.p_away, p.tip_home, p.tip_away,
                   p.missing_home, p.missing_away, v.stadium,
                   w.temp_c, w.precip_mm, w.wind_kmh
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
            LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
            LEFT JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
            LEFT JOIN match_venue v ON v.competition = 'BL' AND v.match_id = m.id
            LEFT JOIN match_weather w ON w.competition = 'BL' AND w.match_id = m.id AND w.kind = 'gemessen'
            WHERE m.finished AND s.start_year >= :first AND {where}"""), {"v": MODEL_VERSION, "first": MODEL_FIRST_SEASON, **params})]
        if not matches:
            return []
        ids = [m["id"] for m in matches]
        goals, starters, reds, stats = {}, {}, {}, {}
        for r in conn.execute(text("""SELECT match_id, minute, player, player_assisted, situation, shot_type, xg, result, team_id
                                       FROM shot WHERE match_id = ANY(:ids) AND result IN ('Goal', 'OwnGoal')
                                       ORDER BY match_id, minute, id"""), {"ids": ids}):
            goals.setdefault(r.match_id, []).append(dict(r._mapping))
        for r in conn.execute(text("""SELECT pm.match_id, p.name, pm.started, pm.red_cards, t.name AS team
                                       FROM player_match pm JOIN player p ON p.id = pm.player_id JOIN team t ON t.id = pm.team_id
                                       WHERE pm.match_id = ANY(:ids)"""), {"ids": ids}):
            if r.started:
                starters.setdefault(r.match_id, set()).add(r.name)
            if r.red_cards:
                reds.setdefault(r.match_id, []).append({"player": r.name, "team": short(r.team)})
        for r in conn.execute(text("""SELECT x.match_id, x.is_home, x.xg, x.shots, x.shots_on_target, x.big_chances, x.corners, x.ppda
                                       FROM match_team_stats x WHERE x.match_id = ANY(:ids)"""), {"ids": ids}):
            stats.setdefault(r.match_id, {})["home" if r.is_home else "away"] = dict(r._mapping)
    out = []
    for m in matches:
        m["home_short"], m["away_short"] = short(m["home"]), short(m["away"])
        m["weather"] = {"temp_c": m.pop("temp_c"), "precip_mm": m.pop("precip_mm"), "wind_kmh": m.pop("wind_kmh")}
        out.append((m["id"], m, build(m, goals.get(m["id"], []), starters.get(m["id"], set()),
                                      reds.get(m["id"], []), stats.get(m["id"], {}))))
    return out


def generate(only_missing: bool = True, recent_days: int = 14) -> int:
    """Berichte für gespielte Spiele schreiben: fehlende und (neu) die der letzten Tage, weil xG und Statistik
    einige Tage nachträglich kommen können. Ändert sich der Text, wird das Embedding neu berechnet."""
    where = ("(NOT EXISTS (SELECT 1 FROM match_report r WHERE r.match_id = m.id) "
             "OR m.kickoff > now() - make_interval(days => :d))") if only_missing else "true"
    rows = _load(where, {"d": recent_days})
    with engine.begin() as conn:
        for match_id, m, body in rows:
            conn.execute(text("""
                INSERT INTO match_report (match_id, season, matchday, kickoff, home_id, away_id, text, updated_at)
                VALUES (:id, :season, :md, :k, :h, :a, :t, now())
                ON CONFLICT (match_id) DO UPDATE SET text = EXCLUDED.text, updated_at = now(),
                    embedding = CASE WHEN match_report.text = EXCLUDED.text THEN match_report.embedding END"""),
                {"id": match_id, "season": m["season"], "md": m["matchday"], "k": m["kickoff"],
                 "h": m["home_id"], "a": m["away_id"], "t": body})
    return len(rows)


def embed(texts: list[str], prefix: str = DOC_PREFIX) -> list[list[float]]:
    """Embeddings über LM Studio (OpenAI-kompatibel)."""
    resp = httpx.post(f"{LOCAL_LLM_URL}/embeddings", json={"model": EMBED_MODEL, "input": [prefix + t for t in texts]},
                      timeout=120)
    resp.raise_for_status()
    return [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]


def embed_missing(batch: int = 64, progress=None) -> int:
    """Embeddings für Berichte ohne Vektor nachtragen. Ohne LM Studio: Fehler, die Volltextsuche geht weiter."""
    total = 0
    while True:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT match_id, text FROM match_report WHERE embedding IS NULL ORDER BY kickoff LIMIT :n"),
                                {"n": batch}).all()
        if not rows:
            return total
        vectors = embed([r.text for r in rows])
        with engine.begin() as conn:
            for r, v in zip(rows, vectors):
                conn.execute(text("UPDATE match_report SET embedding = CAST(:v AS vector), embed_model = :m WHERE match_id = :id"),
                             {"v": json.dumps(v), "m": EMBED_MODEL, "id": r.match_id})
        total += len(rows)
        if progress:
            progress(total)


RRF_K = 60  # Reciprocal Rank Fusion: Gewicht der Ränge aus Vektor- und Volltextsuche
VECTOR_WEIGHT = 0.5  # die Berichte sind gleich aufgebaut, die Vektorsuche bringt mehr Rauschen als die Stichworte


def search(query: str, team_id: int | None = None, season: int | None = None, limit: int = 8,
           newest_first: bool = False) -> list[dict]:
    """Berichte zur Frage: Vektorsuche (Bedeutung, Embedding aus LM Studio) und Volltextsuche (Deutsch) getrennt,
    Ränge mit Reciprocal Rank Fusion kombiniert. Ohne LM Studio nur Volltext. Optional nach Team und Saison
    gefiltert; ohne Frage die jüngsten Spiele des Filters. newest_first: unter den Volltexttreffern die jüngsten
    (für Fragen wie "wann zuletzt …")."""
    filters, params = ["true"], {"n": max(limit * 4, 30)}
    if team_id:
        filters.append(":t IN (r.home_id, r.away_id)")
        params["t"] = team_id
    if season:
        filters.append("r.season = :y")
        params["y"] = season
    where = " AND ".join(filters)
    ranks: dict[int, float] = {}
    methods = []
    with engine.connect() as conn:
        if not query.strip():
            ids = [r[0] for r in conn.execute(text(f"SELECT match_id FROM match_report r WHERE {where} "
                                                   "ORDER BY kickoff DESC LIMIT :n"), params)]
            ranks = {i: -k for k, i in enumerate(ids)}
            methods.append("neueste")
        else:
            fts = conn.execute(text(f"""SELECT match_id FROM match_report r WHERE {where}
                                        AND r.tsv @@ websearch_to_tsquery('german', :q)
                                        ORDER BY ts_rank(r.tsv, websearch_to_tsquery('german', :q)) DESC LIMIT :n"""),
                               {**params, "q": query}).all()
            if not fts:  # Volltext mit allen Wörtern zu streng: mit ODER
                fts = conn.execute(text(f"""SELECT match_id FROM match_report r WHERE {where}
                                            AND r.tsv @@ to_tsquery('german', :q)
                                            ORDER BY ts_rank(r.tsv, to_tsquery('german', :q)) DESC LIMIT :n"""),
                                   {**params, "q": " | ".join(w for w in query.replace("'", " ").split() if w.isalnum()) or "x"}).all()
            for k, (i,) in enumerate(fts):
                ranks[i] = ranks.get(i, 0) + 1 / (RRF_K + k)
            methods.append("volltext")
            if newest_first and fts:  # jüngste Volltexttreffer statt der relevantesten
                sql = f"""SELECT match_id, text FROM match_report r WHERE {where}
                          AND r.tsv @@ websearch_to_tsquery('german', :q) ORDER BY kickoff DESC LIMIT 200"""
                found = conn.execute(text(sql), {**params, "q": query}).all()
                if team_id:  # mit Team: nur Spiele, in denen das gesuchte Ereignis diesem Team gehört
                    short = _team_short(conn, team_id)
                    found = [r for r in found if _owns(r.text, short, query)] or found
                newest = [r.match_id for r in found[:limit]]
                if newest:
                    ranks = {i: -k for k, i in enumerate(newest)}
                    methods.append("neueste")
            try:
                if "neueste" in methods:
                    raise KeyError  # keine Vektorsuche nötig
                vec = json.dumps(embed([query], QUERY_PREFIX)[0])
                vrows = conn.execute(text(f"""SELECT match_id FROM match_report r WHERE {where} AND r.embedding IS NOT NULL
                                              ORDER BY r.embedding <=> CAST(:q AS vector) LIMIT :n"""),
                                     {**params, "q": vec}).all()
                for k, (i,) in enumerate(vrows):
                    ranks[i] = ranks.get(i, 0) + VECTOR_WEIGHT / (RRF_K + k)
                methods.append("vektor")
            except (httpx.HTTPError, KeyError, IndexError):
                pass
        if team_id and "neueste" not in methods and ranks:
            # mit Teamfilter: Berichte bevorzugen, deren Stichworte das Ereignis diesem Team zuschreiben
            # ("Comeback von Gladbach" statt "Comeback von Mainz" im Spiel gegen Gladbach)
            short = _team_short(conn, team_id)
            for r in conn.execute(text("SELECT match_id, text FROM match_report WHERE match_id = ANY(:ids)"), {"ids": list(ranks)}):
                if _owns(r.text, short, query):
                    ranks[r.match_id] += 1
        top = sorted(ranks, key=lambda i: -ranks[i])[:limit]
        rows = {r.match_id: r for r in conn.execute(text(
            "SELECT match_id, kickoff, season, matchday, text FROM match_report WHERE match_id = ANY(:ids)"), {"ids": top})}
    return [{"match_id": i, "datum": rows[i].kickoff.astimezone(BERLIN).date().isoformat(), "saison": rows[i].season,
             "spieltag": rows[i].matchday, "bericht": rows[i].text, "relevanz": round(ranks[i], 4),
             "suche": "+".join(methods), "link": f"/spiel/{i}"} for i in top]


def _owns(report_text: str, team: str, query: str) -> bool:
    """Schreiben die Stichworte das gesuchte Ereignis diesem Team zu? Eine Teilaussage muss ein Wort der Suche
    enthalten (Wortanfang, 5 Zeichen) und das Team nennen ("Gladbach gewinnt nach Rückstand"), nicht nur
    "Niederlage von Gladbach" neben "Heimsieg von Freiburg"."""
    line = next((x for x in report_text.splitlines() if x.startswith("Stichworte:")), "")
    team_words = {w.lower()[:5] for w in team.split()}
    stems = [s for s in (w.lower()[:5] for w in query.split() if len(w) >= 4) if s not in team_words
             and s not in ("borus", "spiel")]  # Teamname zählt nicht als Suchwort
    for clause in line.removeprefix("Stichworte:").replace(";", ",").split(","):  # jede Teilaussage einzeln
        c = clause.lower()
        if (f"von {team.lower()}" in c or c.strip().startswith(team.lower())) and (not stems or any(s in c for s in stems)):
            return True
    return False


def _team_short(conn, team_id: int) -> str:
    """Kurzname wie in den Stichworten ("Gladbach")."""
    from fussballdb.ingest.team_mapping import COLLOQUIAL

    name = conn.scalar(text("SELECT name FROM team WHERE id = :t"), {"t": team_id})
    return (COLLOQUIAL.get(name) or [name])[0]


def report(match_id: int) -> str | None:
    with engine.connect() as conn:
        return conn.scalar(text("SELECT text FROM match_report WHERE match_id = :id"), {"id": match_id})

