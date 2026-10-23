"""REST-API über Datenbank und Prognosemodell (für die Web-App)."""

import json
import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from fussballdb.assistant.tools import Toolbox, _rows
from fussballdb.config import TIPP_PUNKTE
from fussballdb.ingest.tv import for_matches as tv_for
from fussballdb.ingest.venues import for_matches as venues_for
from fussballdb.model.tips import apply_rule
from fussballdb.model.tips import summary as tip_summary
from fussballdb.maintenance import STATUS, check, ensure_in_background
from fussballdb.model.ensemble import MODEL_VERSION

toolbox = Toolbox()


def _reload_model() -> None:
    toolbox._model = None  # beim nächsten Aufruf mit den neuen Daten trainieren


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Beim Start prüfen, ob Daten fehlen oder veraltet sind; läuft im Hintergrund,
    # die API ist sofort erreichbar. Abschalten mit AUTO_UPDATE=0.
    if os.environ.get("AUTO_UPDATE", "1") != "0":
        ensure_in_background(on_done=_reload_model)
    yield


app = FastAPI(title="fussballdb", description="Bundesliga-Daten, xG und Prognosen", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
def invalid_request(_, exc: RequestValidationError):
    # ohne die Eingaben zurückzuschicken (beim Kickbase-Login stünde dort das Passwort)
    fields = sorted({".".join(str(x) for x in e.get("loc", [])[1:]) for e in exc.errors()})
    return JSONResponse(status_code=422, content={"detail": f"Ungültige Anfrage: {', '.join(fields) or 'Eingabe'}"})


@app.exception_handler(ValueError)
def value_error(_, exc: ValueError):
    # z. B. unbekannter Teamname oder unzulässige SQL-Abfrage
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/teams")
def teams():
    return _rows(
        """
        SELECT DISTINCT t.id, t.name
        FROM team t JOIN match m ON t.id IN (m.home_team_id, m.away_team_id)
        JOIN season s ON s.id = m.season_id
        WHERE s.start_year = (SELECT max(start_year) FROM season)
        ORDER BY t.name
        """
    )


@app.get("/upcoming")
def upcoming(limit: Annotated[int, Query(ge=1, le=50)] = 9):
    return toolbox.get_upcoming_matches(limit)


@app.get("/table")
def table(season: int | None = None):
    return toolbox.get_table(season)


@app.get("/teams/{team}/form")
def team_form(team: str, last_n: Annotated[int, Query(ge=1, le=40)] = 8):
    return toolbox.get_team_form(team, last_n)


@app.get("/teams/{team}/absences")
def team_absences(team: str):
    return toolbox.get_absences(team)


@app.get("/h2h")
def head_to_head(team_a: str, team_b: str):
    return toolbox.get_head_to_head(team_a, team_b)


@app.get("/predict")
def predict(home: str, away: str):
    return toolbox.predict_match(home, away)


@app.get("/predictions/review")
def predictions_review(limit: Annotated[int, Query(ge=1, le=200)] = 50):
    """Gespeicherte Prognosen beendeter Spiele gegen das Ergebnis."""
    return _rows(
        """
        SELECT m.matchday, m.kickoff, ht.name AS home, at.name AS away, m.home_goals, m.away_goals,
               round(p.p_home::numeric, 3) AS p_home, round(p.p_draw::numeric, 3) AS p_draw,
               round(p.p_away::numeric, 3) AS p_away
        FROM prediction p JOIN match m ON m.id = p.match_id
        JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
        WHERE m.finished ORDER BY m.kickoff DESC LIMIT :limit
        """,
        limit=limit,
    )


WIN_TENDENCY, WIN_DIFF, EXACT, DRAW_TENDENCY = TIPP_PUNKTE
POINTS_SQL = f"""
    CASE WHEN NOT m.finished OR p.tip_home IS NULL THEN NULL
         WHEN p.tip_home = m.home_goals AND p.tip_away = m.away_goals THEN {EXACT}
         WHEN sign(p.tip_home - p.tip_away) <> sign(m.home_goals - m.away_goals) THEN 0
         WHEN m.home_goals = m.away_goals THEN {DRAW_TENDENCY}
         WHEN p.tip_home - p.tip_away = m.home_goals - m.away_goals THEN {WIN_DIFF}
         ELSE {WIN_TENDENCY} END
"""


@app.get("/seasons")
def seasons():
    """Saisons mit Anzahl Spieltage und aktuellem Spieltag (erster mit offenen Spielen)."""
    return _rows(
        """
        SELECT s.start_year, s.label, max(m.matchday) AS matchdays,
               coalesce(min(m.matchday) FILTER (WHERE NOT m.finished), max(m.matchday)) AS current_matchday,
               bool_and(m.finished) AS finished
        FROM season s JOIN match m ON m.season_id = s.id
        GROUP BY s.start_year, s.label ORDER BY s.start_year DESC
        """
    )


_SCORER_CACHE: dict = {}


def _scorers() -> dict:
    """Torschützen-Prognose für alle offenen Spiele der Saison, 10 Minuten zwischengespeichert."""
    import time

    from fussballdb.features.scorers import scorers

    if _SCORER_CACHE.get("t", 0) > time.time() - 600:
        return _SCORER_CACHE["data"]
    data = scorers(matchdays=34)
    _SCORER_CACHE.update(t=time.time(), data=data)
    return data


def _bl_games(where: str, **params) -> list[dict]:
    """Bundesliga-Spiele mit Ergebnis, xG, gespeicherter Prognose, Tipp und Tipp-Punkten."""
    return _rows(
        f"""
        SELECT m.id, m.kickoff, s.start_year AS season, s.label AS season_label, m.matchday,
               m.home_team_id, m.away_team_id, ht.name AS home, at.name AS away,
               m.home_goals, m.away_goals, m.finished,
               hs.xg AS home_xg, as_.xg AS away_xg,
               round(p.p_home::numeric, 3) AS p_home, round(p.p_draw::numeric, 3) AS p_draw,
               round(p.p_away::numeric, 3) AS p_away,
               round(p.exp_home_goals::numeric, 2) AS exp_home_goals, round(p.exp_away_goals::numeric, 2) AS exp_away_goals,
               p.tip_home, p.tip_away, p.basis, p.as_of, p.missing_home, p.missing_away, p.explanation,
               p.score_probs, {POINTS_SQL} AS points
        FROM match m JOIN season s ON s.id = m.season_id
        JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
        LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
        LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
        LEFT JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
        WHERE {where}
        ORDER BY m.matchday, m.kicktipp_pos NULLS LAST, m.kickoff, m.id  -- Reihenfolge wie bei Kicktipp
        """,
        v=MODEL_VERSION, **params,
    )


def _tip_round(slug: str | None) -> dict:
    """Tipprunde nach Kurzname, ohne Angabe die Standardrunde; ohne angelegte Runden die Regel aus config."""
    rows = _rows("""SELECT slug, name, url, win_tendency, win_diff, exact, draw_tendency, lead_minutes, bonus_points,
                            is_default FROM tip_round ORDER BY is_default DESC, id""")
    rnd = next((r for r in rows if r["slug"] == slug), None) if slug else (rows[0] if rows else None)
    if slug and rnd is None:
        raise ValueError(f"Tipprunde {slug!r} gibt es nicht.")
    if rnd is None:
        return {"slug": None, "name": "Standard", "rule": tuple(TIPP_PUNKTE), "bonus_points": None}
    return {**rnd, "rule": (rnd["win_tendency"], rnd["win_diff"], rnd["exact"], rnd["draw_tendency"])}


def _punkteregel(rule=TIPP_PUNKTE) -> dict:
    return {"sieg_tendenz": rule[0], "sieg_tordifferenz": rule[1], "exakt": rule[2], "remis_tendenz": rule[3]}


def _round_info(rnd: dict) -> dict:
    return {k: rnd.get(k) for k in ("slug", "name", "url", "lead_minutes", "bonus_points")}


def _decorate_bl(games: list[dict], rule=TIPP_PUNKTE) -> None:
    """Begründung als Liste, TV-Sender und (bei offenen Spielen) wahrscheinliche Torschützen ergänzen; Tipp und
    Punkte nach der Punkteregel der gewählten Tipprunde."""
    tv = tv_for("BL", [g["id"] for g in games])
    places = venues_for("BL", [g["id"] for g in games])
    scorers = _scorers() if any(not g["finished"] for g in games) else {}
    for g in games:
        g["explanation"] = json.loads(g["explanation"]) if g["explanation"] else []
        g["tv"] = tv.get(g["id"], {})
        g["ort"] = places.get(g["id"])
        sc = scorers.get(g["id"], {})
        if sc:
            g["torschuetzen"] = {"home": sc.get(g["home_team_id"], []), "away": sc.get(g["away_team_id"], [])}
        apply_rule(g, rule)


@app.get("/matchday/{season}/{matchday}")
def matchday(season: int, matchday: int, runde: str | None = None):
    """Alle Spiele eines Spieltags mit Ergebnis, gespeicherter Prognose, Tipp und Tipp-Punkten nach der Punkteregel
    der Tipprunde (runde = Kurzname, ohne Angabe die Standardrunde). Dazu die Bilanz des Spieltags und der Saison
    bis dahin."""
    rnd = _tip_round(runde)
    rule = rnd["rule"]
    games = _bl_games("s.start_year = :y AND m.matchday = :md", y=season, md=matchday)
    if not games:
        raise ValueError(f"Spieltag {matchday} der Saison {season} gibt es nicht.")
    if tuple(rule) != tuple(TIPP_PUNKTE):
        # Tipps nach anderer Regel: Saisonbilanz aus den Ergebnis-Wahrscheinlichkeiten nachrechnen
        played = _bl_games("s.start_year = :y AND m.matchday <= :md AND m.finished", y=season, md=matchday)
        pts = [apply_rule(g, rule)["points"] for g in played if g["tip_home"] is not None]
        season_summary = tip_summary([p for p in pts if p is not None], rule)
    else:
        season_summary = None
    season_summary = season_summary or _rows(
        f"""
        SELECT count(*) FILTER (WHERE m.finished AND p.tip_home IS NOT NULL) AS spiele,
               coalesce(sum({POINTS_SQL}), 0) AS punkte,
               count(*) FILTER (WHERE ({POINTS_SQL}) > 0) AS tendenz,
               count(*) FILTER (WHERE ({POINTS_SQL}) = {EXACT}) AS exakt
        FROM match m JOIN season s ON s.id = m.season_id
        LEFT JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
        WHERE s.start_year = :y AND m.matchday <= :md
        """,
        y=season, md=matchday, v=MODEL_VERSION,
    )[0]
    _decorate_bl(games, rule)
    scored = [g["points"] for g in games if g["points"] is not None]
    return {
        "season": season,
        "matchday": matchday,
        "games": games,
        "summary": tip_summary(scored, rule),
        "punkteregel": _punkteregel(rule),
        "tipprunde": _round_info(rnd),
        "season_summary": season_summary,
    }


# Wettbewerbe mit eigener Prognose aus dem Europa-Modell (model/europe.py)
COMPETITIONS = {"CL": "Champions League", "D2": "2. Bundesliga", "DFB": "DFB-Pokal"}


def _comp(comp: str) -> str:
    comp = comp.upper()
    if comp not in COMPETITIONS:
        raise ValueError(f"Unbekannter Wettbewerb {comp}. Möglich: {', '.join(COMPETITIONS)}")
    return comp


@app.get("/cl/rounds")
def cl_rounds():
    """Champions-League-Runden aller Saisons (Spieltage der Ligaphase, Play-offs, K.-o.-Runden) mit der
    aktuellen Runde je Saison (erste mit offenen Spielen)."""
    return comp_rounds("CL")


@app.get("/eu/{comp}/rounds")
def comp_rounds(comp: str):
    """Runden aller Saisons eines Wettbewerbs (CL, D2 = 2. Bundesliga, DFB = DFB-Pokal) mit der aktuellen Runde."""
    comp = _comp(comp)
    rows = _rows(
        """
        SELECT season, round_no, min(round_name) AS round_name, count(*) AS spiele,
               bool_and(finished) AS finished, min(kickoff) AS start
        FROM eu_match WHERE competition = :c AND season >= 2024
        GROUP BY season, round_no ORDER BY season DESC, round_no
        """, c=comp,
    )
    seasons: dict[int, dict] = {}
    for r in rows:
        s = seasons.setdefault(r["season"], {"season": r["season"], "label": f"{r['season']}/{(r['season'] + 1) % 100:02d}",
                                             "rounds": [], "current_round": None})
        s["rounds"].append({k: r[k] for k in ("round_no", "round_name", "spiele", "finished", "start")})
        if s["current_round"] is None and not r["finished"]:
            s["current_round"] = r["round_no"]
    for s in seasons.values():
        s["current_round"] = s["current_round"] or s["rounds"][-1]["round_no"]
    return list(seasons.values())


def _cl_absences(match_ids: list[int]) -> dict[tuple[int, str], str]:
    """Aktuelle Ausfälle der Teams offener CL-Spiele als Begründungszeile (nur Anzeige, nicht im Modell)."""
    if not match_ids:
        return {}
    rows = _rows(
        """
        SELECT m.id AS match_id, t.name AS team, a.player_name, a.kind, a.value_share
        FROM eu_match m JOIN eu_team t ON t.id IN (m.home_id, m.away_id)
        JOIN eu_absence a ON a.team_id = t.id AND a.active
        WHERE m.id = ANY(:ids)
        ORDER BY a.value_share DESC NULLS LAST
        """,
        ids=match_ids,
    )
    grouped: dict[tuple[int, str], list[dict]] = {}
    for r in rows:
        items = grouped.setdefault((r["match_id"], r["team"]), [])
        same = next((i for i in items if i["player_name"] == r["player_name"]), None)
        if same:  # verletzt und gesperrt zugleich: einmal nennen
            same["kind"] = "gesperrt" if "gesperrt" in (same["kind"], r["kind"]) else same["kind"]
        else:
            items.append(dict(r))
    out = {}
    for key, items in grouped.items():
        names = [i["player_name"] + (" (gesperrt)" if i["kind"] == "gesperrt" else "") for i in items]
        share = sum(i["value_share"] or 0 for i in items)
        shown = ", ".join(names[:4]) + (f" und {len(names) - 4} weitere" if len(names) > 4 else "")
        out[key] = (f"Es fehlen bei {key[1]}: {shown}"
                    + (f" (zusammen {round(100 * share)} % des Kaderwerts, nicht eingerechnet)" if share else ""))
    return out


@app.get("/cl/table/{season}")
def cl_table(season: int):
    """Tabelle der CL-Ligaphase mit Modell-Platz (platz_diff > 0 = besser als laut Prognosen erwartet) und,
    solange Spiele offen sind, der Hochrechnung (prognose_platz, erw_punkte, p_achtelfinale, p_playoffs, p_aus)."""
    return comp_table("CL", season)


@app.get("/eu/{comp}/table/{season}")
def comp_table(comp: str, season: int):
    """Tabelle (CL: Ligaphase, D2: 2. Bundesliga) mit Modell-Platz und Hochrechnung samt Zonen-Chancen."""
    from fussballdb.model.cl_table import ZONES, table

    comp = _comp(comp)
    if comp not in ZONES:
        raise ValueError(f"Für {COMPETITIONS[comp]} gibt es keine Tabelle.")
    rows = table(season, comp)
    if not rows:
        raise ValueError(f"Keine Tabelle für {COMPETITIONS[comp]} {season}.")
    zones = [{"key": k, "label": label, "von": a, "bis": b} for k, label, a, b in ZONES[comp]["zones"]]
    return {"season": season, "label": f"{season}/{(season + 1) % 100:02d}", "rows": rows, "zonen": zones,
            "wettbewerb": COMPETITIONS[comp]}


@app.get("/cl/round/{season}/{round_no}")
def cl_round(season: int, round_no: int):
    """Spiele einer CL-Runde mit Prognose, Tipp und Tipp-Punkten."""
    return comp_round("CL", season, round_no)


def _eu_games(where: str, **params) -> list[dict]:
    """Spiele aus dem Europa-Modell mit Prognose, Tipp und Tipp-Punkten. Bei gespielten Spielen zählt die
    Live-Prognose von vor dem Anpfiff, sonst die Rückblick-Prognose."""
    return _rows(
        f"""
        SELECT m.id, m.kickoff, m.competition, m.season, m.round_no, m.round_name, m.neutral,
               m.home_id AS home_team_id, m.away_id AS away_team_id, ht.name AS home, at.name AS away,
               m.home_goals, m.away_goals, m.finished,
               round(m.home_xg::numeric, 2) AS home_xg, round(m.away_xg::numeric, 2) AS away_xg,
               round(p.p_home::numeric, 3) AS p_home, round(p.p_draw::numeric, 3) AS p_draw,
               round(p.p_away::numeric, 3) AS p_away,
               round(p.exp_home_goals::numeric, 2) AS exp_home_goals, round(p.exp_away_goals::numeric, 2) AS exp_away_goals,
               round(p.elo_home::numeric) AS elo_home, round(p.elo_away::numeric) AS elo_away,
               p.value_home, p.value_away, p.tip_home, p.tip_away, p.basis, p.as_of, p.explanation,
               {POINTS_SQL} AS points
        FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
        LEFT JOIN LATERAL (
            SELECT * FROM eu_prediction x WHERE x.match_id = m.id
            ORDER BY (x.basis = 'live' AND x.as_of <= m.kickoff) DESC, (x.basis = 'rueckblick') DESC LIMIT 1
        ) p ON true
        WHERE {where}
        ORDER BY m.kickoff, m.id
        """,
        **params,
    )


def _decorate_eu(comp: str, games: list[dict]) -> None:
    """Begründung als Liste, TV-Sender und (CL, offene Spiele) die aktuellen Ausfälle als Begründungszeile."""
    tv = tv_for(comp, [g["id"] for g in games])
    places = venues_for(comp, [g["id"] for g in games])
    missing = _cl_absences([g["id"] for g in games if not g["finished"]]) if comp == "CL" else {}
    for g in games:
        g["explanation"] = json.loads(g["explanation"]) if g["explanation"] else []
        g["tv"] = tv.get(g["id"], {})
        g["ort"] = places.get(g["id"])
        for team in (g["home"], g["away"]):
            if (g["id"], team) in missing:
                g["explanation"].append(missing[(g["id"], team)])


@app.get("/eu/{comp}/round/{season}/{round_no}")
def comp_round(comp: str, season: int, round_no: int):
    """Spiele einer Runde (CL, 2. Bundesliga, DFB-Pokal) mit Prognose, Tipp und Tipp-Punkten. Bei gespielten
    Spielen zählt die Live-Prognose von vor dem Anpfiff, sonst die Rückblick-Prognose (Stand vor der Runde)."""
    comp = _comp(comp)
    games = _eu_games("m.competition = :c AND m.season = :y AND m.round_no = :r", y=season, r=round_no, c=comp)
    if not games:
        raise ValueError(f"Runde {round_no} der Saison {season} gibt es im Wettbewerb {COMPETITIONS[comp]} nicht.")
    _decorate_eu(comp, games)
    scored = [g for g in games if g["points"] is not None]
    season_rows = _rows(
        f"""
        SELECT {POINTS_SQL} AS points
        FROM eu_match m
        LEFT JOIN LATERAL (
            SELECT * FROM eu_prediction x WHERE x.match_id = m.id
            ORDER BY (x.basis = 'live' AND x.as_of <= m.kickoff) DESC, (x.basis = 'rueckblick') DESC LIMIT 1
        ) p ON true
        WHERE m.competition = :c AND m.season = :y AND m.round_no <= :r
        """,
        y=season, r=round_no, c=comp,
    )
    season_scored = [r["points"] for r in season_rows if r["points"] is not None]

    def summary(points: list[int]) -> dict:
        return {"spiele": len(points), "punkte": sum(points), "tendenz": sum(1 for p in points if p > 0),
                "exakt": sum(1 for p in points if p == EXACT)}

    return {
        "season": season, "round_no": round_no, "round_name": games[0]["round_name"], "games": games,
        "wettbewerb": COMPETITIONS[comp],
        "summary": summary([g["points"] for g in scored]), "season_summary": summary(season_scored),
        "punkteregel": {"sieg_tendenz": WIN_TENDENCY, "sieg_tordifferenz": WIN_DIFF, "exakt": EXACT,
                        "remis_tendenz": DRAW_TENDENCY},
    }


FORM_GAMES = 6
# Wettbewerbe im Europa-Modell (football-data-Kürzel und OpenLigaDB) für die Form-Liste
COMP_NAMES = {
    "D1": "Bundesliga", "D2": "2. Bundesliga", "D3": "3. Liga", "DFB": "DFB-Pokal", "CL": "Champions League",
    "EL": "Europa League", "E0": "Premier League", "SP1": "LaLiga", "I1": "Serie A", "F1": "Ligue 1",
    "N1": "Eredivisie", "P1": "Liga Portugal", "B1": "Pro League", "T1": "Süper Lig", "SC0": "Premiership",
    "G1": "Super League GR", "AUT": "Bundesliga AT", "SWZ": "Super League CH", "DNK": "Superliga",
    "NOR": "Eliteserien", "SWE": "Allsvenskan", "POL": "Ekstraklasa", "ROU": "Liga 1",
}


def _h2h_summary(games: list[dict], home: str) -> dict:
    """Bilanz der direkten Duelle aus Sicht des heutigen Heimteams."""
    s = {"spiele": len(games), "siege_heim": 0, "remis": 0, "siege_gast": 0, "tore_heim": 0, "tore_gast": 0}
    for g in games:
        own, opp = (g["home_goals"], g["away_goals"]) if g["home"] == home else (g["away_goals"], g["home_goals"])
        s["tore_heim"] += own
        s["tore_gast"] += opp
        s["siege_heim" if own > opp else "siege_gast" if own < opp else "remis"] += 1
    return s


def _bl_form(team_id: int, before) -> list[dict]:
    return _rows(
        """
        SELECT m.id, m.kickoff, m.matchday, CASE WHEN m.home_team_id = :t THEN 'H' ELSE 'A' END AS ort,
               opp.name AS gegner, own.goals AS tore, o.goals AS gegentore, own.xg, o.xg AS xga
        FROM match m
        JOIN match_team_stats own ON own.match_id = m.id AND own.team_id = :t
        JOIN match_team_stats o ON o.match_id = m.id AND o.team_id <> :t
        JOIN team opp ON opp.id = o.team_id
        WHERE m.finished AND m.kickoff < :k ORDER BY m.kickoff DESC LIMIT :n
        """, t=team_id, k=before, n=FORM_GAMES)


def _lineup(team_id: int) -> list[dict]:
    """Voraussichtliche Startelf laut letztem Ligainsider-Abruf (Reihe 1 = Tor)."""
    return _rows(
        """
        SELECT position_row AS reihe, player_name AS name FROM lineup_snapshot
        WHERE team_id = :t AND status = 'vorschau' AND role = 'start'
          AND fetched_at = (SELECT max(fetched_at) FROM lineup_snapshot WHERE team_id = :t AND status = 'vorschau')
        ORDER BY position_row, id
        """, t=team_id)


def _implied(odds: list[dict]) -> list[dict]:
    """Quoten in Wahrscheinlichkeiten ohne Buchmacher-Marge umrechnen."""
    out = []
    for o in odds:
        if not (o["home"] and o["draw"] and o["away"]):
            continue
        inv = [1 / o["home"], 1 / o["draw"], 1 / o["away"]]
        total = sum(inv)
        out.append({**o, "p_home": round(inv[0] / total, 3), "p_draw": round(inv[1] / total, 3),
                    "p_away": round(inv[2] / total, 3)})
    return out


@app.get("/match/{match_id}")
def match_detail(match_id: int, runde: str | None = None):
    """Ein Bundesliga-Spiel im Detail: Prognose wie auf der Spieltag-Kachel, dazu Form beider Teams vor dem Spiel,
    direkte Duelle vor dem Spiel, Tabelle, Ausfälle, voraussichtliche Aufstellung, Marktquoten und (gespielt) die Spielstatistik."""
    games = _bl_games("m.id = :id", id=match_id)
    if not games:
        raise ValueError(f"Spiel {match_id} gibt es nicht.")
    rnd = _tip_round(runde)
    _decorate_bl(games, rnd["rule"])
    g = games[0]
    h, a = g["home_team_id"], g["away_team_id"]
    h2h = _rows(
        """
        SELECT m.id, m.kickoff, s.label AS saison, ht.name AS home, at.name AS away, m.home_goals, m.away_goals,
               hs.xg AS home_xg, as_.xg AS away_xg
        FROM match m JOIN season s ON s.id = m.season_id
        JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
        LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
        LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
        WHERE m.finished AND m.kickoff < :k
          AND ((m.home_team_id = :h AND m.away_team_id = :a) OR (m.home_team_id = :a AND m.away_team_id = :h))
        ORDER BY m.kickoff DESC
        """, k=g["kickoff"], h=h, a=a)
    table = {r["name"]: {**r, "platz": i} for i, r in enumerate(toolbox._table_rows(g["season"]), 1)}
    stats = _rows(
        """
        SELECT is_home, goals, xg, shots, shots_on_target, big_chances, corners, fouls, yellow_cards, red_cards,
               ppda, xpts
        FROM match_team_stats WHERE match_id = :id ORDER BY is_home DESC
        """, id=match_id) if g["finished"] else []
    odds = _implied(_rows(
        """SELECT bookmaker, is_closing, home, draw, away FROM odds
           WHERE match_id = :id AND bookmaker IN ('Avg', 'B365') ORDER BY bookmaker, is_closing""", id=match_id))
    return {
        "wettbewerb": "Bundesliga", "game": g, "punkteregel": _punkteregel(rnd["rule"]), "tipprunde": _round_info(rnd),
        "form": {"home": _bl_form(h, g["kickoff"]), "away": _bl_form(a, g["kickoff"])},
        "h2h": h2h, "h2h_summary": _h2h_summary(h2h, g["home"]),
        "tabelle": {"home": table.get(g["home"]), "away": table.get(g["away"]), "stand": g["season_label"]},
        "ausfaelle": None if g["finished"] else {"home": toolbox.get_absences(g["home"]),
                                                 "away": toolbox.get_absences(g["away"])},
        "aufstellung": None if g["finished"] else {"home": _lineup(h), "away": _lineup(a)},
        "statistik": {"home": stats[0], "away": stats[1]} if len(stats) == 2 else None,
        "quoten": odds,
    }


def _eu_form(team_id: int, before) -> list[dict]:
    rows = _rows(
        """
        SELECT m.id, m.kickoff, m.competition, m.round_name,
               CASE WHEN m.home_id = :t THEN 'H' ELSE 'A' END AS ort, opp.name AS gegner,
               CASE WHEN m.home_id = :t THEN m.home_goals ELSE m.away_goals END AS tore,
               CASE WHEN m.home_id = :t THEN m.away_goals ELSE m.home_goals END AS gegentore,
               CASE WHEN m.home_id = :t THEN m.home_xg ELSE m.away_xg END AS xg,
               CASE WHEN m.home_id = :t THEN m.away_xg ELSE m.home_xg END AS xga
        FROM eu_match m JOIN eu_team opp ON opp.id = CASE WHEN m.home_id = :t THEN m.away_id ELSE m.home_id END
        WHERE m.finished AND m.kickoff < :k AND :t IN (m.home_id, m.away_id)
        ORDER BY m.kickoff DESC LIMIT :n
        """, t=team_id, k=before, n=FORM_GAMES)
    for r in rows:
        r["wettbewerb"] = COMP_NAMES.get(r["competition"], r["competition"])
    return rows


def _eu_absences(team_id: int, name: str) -> list[dict]:
    """Ausfälle eines Teams: Transfermarkt-Liste der CL-Teams, sonst die Bundesliga-Liste, falls es ein
    Bundesligist ist. Format wie /teams/{team}/absences."""
    rows = _rows(
        """
        SELECT DISTINCT ON (player_name) player_name, CASE WHEN kind = 'gesperrt' THEN 'suspension' ELSE 'injury' END AS kind,
               reason, until AS expected_return, value_share
        FROM eu_absence WHERE team_id = :t AND active ORDER BY player_name, (kind = 'gesperrt') DESC
        """, t=team_id)
    if rows:
        return sorted(rows, key=lambda r: -(r["value_share"] or 0))
    if toolbox.teams.find(name) is not None:
        return toolbox.get_absences(name)
    return []


@app.get("/eu/{comp}/match/{match_id}")
def comp_match_detail(comp: str, match_id: int):
    """Ein Spiel aus CL, 2. Bundesliga oder DFB-Pokal im Detail: Prognose wie auf der Kachel, dazu die letzten
    Spiele beider Teams über alle Wettbewerbe, direkte Duelle, Tabelle (CL-Ligaphase, 2. Liga), Kaderwerte und
    Ausfälle."""
    from fussballdb.model.cl_table import ZONES, table

    comp = _comp(comp)
    games = _eu_games("m.id = :id AND m.competition = :c", id=match_id, c=comp)
    if not games:
        raise ValueError(f"Spiel {match_id} gibt es im Wettbewerb {COMPETITIONS[comp]} nicht.")
    _decorate_eu(comp, games)
    g = games[0]
    h, a = g["home_team_id"], g["away_team_id"]
    h2h = _rows(
        """
        SELECT m.id, m.kickoff, m.competition, m.round_name, ht.name AS home, at.name AS away,
               m.home_goals, m.away_goals, m.home_xg, m.away_xg
        FROM eu_match m JOIN eu_team ht ON ht.id = m.home_id JOIN eu_team at ON at.id = m.away_id
        WHERE m.finished AND m.kickoff < :k
          AND ((m.home_id = :h AND m.away_id = :a) OR (m.home_id = :a AND m.away_id = :h))
        ORDER BY m.kickoff DESC
        """, k=g["kickoff"], h=h, a=a)
    for r in h2h:
        r["wettbewerb"] = COMP_NAMES.get(r["competition"], r["competition"])
    tabelle = None
    if comp in ZONES and (g["round_no"] or 0) <= ZONES[comp]["rounds"]:
        rows = {r["name"]: r for r in table(g["season"], comp)}
        tabelle = {"home": rows.get(g["home"]), "away": rows.get(g["away"]),
                   "stand": f"{g['season']}/{(g['season'] + 1) % 100:02d}",
                   "zonen": [{"key": k, "label": label, "von": x, "bis": y} for k, label, x, y in ZONES[comp]["zones"]]}
    values = {r["team_id"]: r["value_eur"] for r in _rows(
        """SELECT DISTINCT ON (team_id) team_id, value_eur FROM eu_squad_value
           WHERE team_id IN (:h, :a) ORDER BY team_id, stichtag DESC""", h=h, a=a)}
    return {
        "wettbewerb": COMPETITIONS[comp], "game": g, "punkteregel": _punkteregel(),
        "form": {"home": _eu_form(h, g["kickoff"]), "away": _eu_form(a, g["kickoff"])},
        "h2h": h2h, "h2h_summary": _h2h_summary(h2h, g["home"]),
        "tabelle": tabelle,
        "kaderwert": {"home": values.get(h), "away": values.get(a)},
        "ausfaelle": None if g["finished"] else {"home": _eu_absences(h, g["home"]), "away": _eu_absences(a, g["away"])},
    }


class TipRoundIn(BaseModel):
    url: str  # Kicktipp-Link oder Kurzname der Runde
    name: str | None = None


@app.get("/tipprunden")
def tip_rounds():
    """Hinterlegte Kicktipp-Tipprunden mit Punkteregel; die erste ist die Standardrunde."""
    return [{**_round_info(r), "punkteregel": _punkteregel(r["rule"]), "standard": bool(r.get("is_default"))}
            for r in (_tip_round(x["slug"]) for x in _rows("SELECT slug FROM tip_round ORDER BY is_default DESC, id"))]


@app.post("/tipprunden")
def add_tip_round(body: TipRoundIn):
    """Tipprunde per Kicktipp-Link anlegen (oder ihre Regel neu lesen)."""
    from fussballdb.db.session import session_scope
    from fussballdb.ingest import kicktipp

    try:
        with session_scope() as s:
            slug = kicktipp.add_round(s, body.url, body.name).slug
    except ValueError:
        raise
    except Exception as exc:  # Seite nicht erreichbar o. Ä.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise ValueError("Diese Tipprunde gibt es bei Kicktipp nicht." if status == 404
                         else "Kicktipp ist gerade nicht erreichbar, bitte später noch einmal.") from None
    return _round_info(_tip_round(slug))


@app.post("/tipprunden/{slug}/standard")
def default_tip_round(slug: str):
    """Tipprunde als Standard setzen (gilt, wenn keine Runde gewählt ist, z. B. im Chat)."""
    from fussballdb.db.session import session_scope

    _tip_round(slug)
    with session_scope() as s:
        s.execute(text("UPDATE tip_round SET is_default = (slug = :s)"), {"s": slug})
    return tip_rounds()


@app.delete("/tipprunden/{slug}")
def delete_tip_round(slug: str):
    from fussballdb.db.session import session_scope

    _tip_round(slug)
    with session_scope() as s:
        s.execute(text("DELETE FROM tip_round WHERE slug = :s"), {"s": slug})
        s.execute(text("""UPDATE tip_round SET is_default = true WHERE id = (SELECT min(id) FROM tip_round)
                          AND NOT EXISTS (SELECT 1 FROM tip_round WHERE is_default)"""))
    return tip_rounds()


_BONUS_CACHE: dict = {}


@app.get("/tipprunden/{slug}/extratipps")
def tip_round_bonus(slug: str):
    """Bonusfragen (Extratipps) der Runde von Kicktipp mit Prognose aus der Saison-Hochrechnung, 1 Std.
    zwischengespeichert. Leer, wenn die Runde keine Bonusfragen hat."""
    import time

    from fussballdb.ingest.kicktipp import bonus_questions
    from fussballdb.maintenance import CURRENT_SEASON
    from fussballdb.model.bonus import forecasts

    rnd = _tip_round(slug)
    if not rnd.get("bonus_points"):
        return {"tipprunde": _round_info(rnd), "fragen": []}
    cached = _BONUS_CACHE.get(slug)
    if cached and cached[0] > time.time() - 3600:
        return cached[1]
    data = {"tipprunde": _round_info(rnd), "fragen": forecasts(bonus_questions(slug), CURRENT_SEASON)}
    _BONUS_CACHE[slug] = (time.time(), data)
    return data


@app.get("/kickbase/projections")
def kickbase_projections(matchdays: Annotated[int, Query(ge=1, le=10)] = 1):
    """Erwartete Ereignisse je Spieler für die nächsten Spieltage (Einsatz, Tore, Vorlagen, Zu null, Gelb)."""
    from fussballdb.features.kickbase_projection import projections

    df = projections(matchdays)
    return json.loads(df.to_json(orient="records", force_ascii=False)) if not df.empty else []


@app.get("/kickbase/aufstellung")
def kickbase_lineup():
    """Beste Elf aus dem eigenen Kickbase-Kader für den nächsten Spieltag, dazu Ausfälle im Kader."""
    from fussballdb.features.kickbase_lineup import lineup

    return json.loads(json.dumps(lineup(), default=str))


class KickbaseLogin(BaseModel):
    email: str
    password: str


class KickbaseLeague(BaseModel):
    league_id: str


@app.get("/kickbase/status")
def kickbase_status():
    """Ist ein Kickbase-Zugang hinterlegt? Gültig bis, Ligen, gewählte Liga (nie das Token)."""
    from fussballdb.ingest import kickbase

    return kickbase.status()


@app.post("/kickbase/login")
def kickbase_login(body: KickbaseLogin):
    """Bei Kickbase anmelden. E-Mail und Passwort gehen nur an Kickbase; gespeichert wird nur das Token.
    Danach werden Markt, Kader und Marktwerte im Hintergrund geladen."""
    from fussballdb.ingest import kickbase

    try:
        kickbase.login(body.email.strip(), body.password)
    except kickbase.KickbaseAuthError as exc:
        raise ValueError(str(exc)) from None
    except Exception:
        raise ValueError("Kickbase ist gerade nicht erreichbar. Bitte später noch einmal versuchen.") from None
    ensure_in_background(on_done=_reload_model, only={"kickbase"}, force=True)
    return kickbase.status()


@app.post("/kickbase/liga")
def kickbase_league(body: KickbaseLeague):
    """Liga wählen, falls das Konto in mehreren Kickbase-Ligen ist; lädt Markt und Kader neu."""
    from fussballdb.ingest import kickbase

    try:
        kickbase.choose_league(body.league_id)
    except kickbase.KickbaseAuthError as exc:
        raise ValueError(str(exc)) from None
    ensure_in_background(on_done=_reload_model, only={"kickbase"}, force=True)
    return kickbase.status()


@app.post("/kickbase/logout")
def kickbase_logout():
    """Kickbase-Zugang löschen (Token entfernen)."""
    from fussballdb.ingest import kickbase

    kickbase.logout()
    return kickbase.status()


class SqlQuery(BaseModel):
    query: str


@app.post("/sql")
def sql(body: SqlQuery):
    """Nur lesende Abfragen, max. 200 Zeilen."""
    return toolbox.run_sql(body.query)


@app.get("/status")
def status():
    """Läuft gerade ein Update? Welche Daten sind aktuell, welche Schritte wären nötig?"""
    return {"update": STATUS | {"results": STATUS["results"][-10:]}, "checks": check()}


@app.post("/update")
def trigger_update(force: bool = False):
    """Update im Hintergrund starten (force=True: alle Schritte außer der Verletzungshistorie)."""
    started = ensure_in_background(on_done=_reload_model, force=force, include_slow=not force)
    return {"started": started, "message": "Update gestartet" if started else "Update läuft bereits"}


@app.post("/reload")
def reload():
    """Prognosemodell nach einem Daten-Update neu trainieren lassen (beim nächsten Aufruf)."""
    toolbox._model = None
    return {"status": "reloaded"}


