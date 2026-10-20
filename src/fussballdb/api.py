"""REST-API über Datenbank und Prognosemodell (für die Web-App)."""

import json
import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fussballdb.assistant.tools import Toolbox, _rows
from fussballdb.config import TIPP_PUNKTE
from fussballdb.ingest.tv import for_matches as tv_for
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


@app.get("/matchday/{season}/{matchday}")
def matchday(season: int, matchday: int):
    """Alle Spiele eines Spieltags mit Ergebnis, gespeicherter Prognose, Tipp und Tipp-Punkten
    nach der Punkteregel der Tipprunde (config.TIPP_PUNKTE). Dazu die Bilanz des Spieltags und der Saison bis dahin."""
    games = _rows(
        f"""
        SELECT m.id, m.kickoff, ht.name AS home, at.name AS away, m.home_goals, m.away_goals, m.finished,
               hs.xg AS home_xg, as_.xg AS away_xg,
               round(p.p_home::numeric, 3) AS p_home, round(p.p_draw::numeric, 3) AS p_draw,
               round(p.p_away::numeric, 3) AS p_away,
               round(p.exp_home_goals::numeric, 2) AS exp_home_goals, round(p.exp_away_goals::numeric, 2) AS exp_away_goals,
               p.tip_home, p.tip_away, p.basis, p.as_of, p.missing_home, p.missing_away, p.explanation,
               {POINTS_SQL} AS points
        FROM match m JOIN season s ON s.id = m.season_id
        JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
        LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
        LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
        LEFT JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
        WHERE s.start_year = :y AND m.matchday = :md
        ORDER BY m.kickoff, m.id
        """,
        y=season, md=matchday, v=MODEL_VERSION,
    )
    if not games:
        raise ValueError(f"Spieltag {matchday} der Saison {season} gibt es nicht.")
    season_summary = _rows(
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
    tv = tv_for("BL", [g["id"] for g in games])
    for g in games:
        g["explanation"] = json.loads(g["explanation"]) if g["explanation"] else []
        g["tv"] = tv.get(g["id"], {})
    scored = [g for g in games if g["points"] is not None]
    return {
        "season": season,
        "matchday": matchday,
        "games": games,
        "summary": {
            "spiele": len(scored),
            "punkte": sum(g["points"] for g in scored),
            "tendenz": sum(1 for g in scored if g["points"] > 0),
            "exakt": sum(1 for g in scored if g["points"] == EXACT),
        },
        "punkteregel": {"sieg_tendenz": WIN_TENDENCY, "sieg_tordifferenz": WIN_DIFF, "exakt": EXACT,
                        "remis_tendenz": DRAW_TENDENCY},
        "season_summary": season_summary,
    }


@app.get("/cl/rounds")
def cl_rounds():
    """Champions-League-Runden aller Saisons (Spieltage der Ligaphase, Play-offs, K.-o.-Runden) mit der
    aktuellen Runde je Saison (erste mit offenen Spielen)."""
    rows = _rows(
        """
        SELECT season, round_no, min(round_name) AS round_name, count(*) AS spiele,
               bool_and(finished) AS finished, min(kickoff) AS start
        FROM eu_match WHERE competition = 'CL' GROUP BY season, round_no ORDER BY season DESC, round_no
        """
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


@app.get("/cl/table/{season}")
def cl_table(season: int):
    """Tabelle der CL-Ligaphase mit Modell-Platz (platz_diff > 0 = besser als laut Prognosen erwartet) und,
    solange Spiele offen sind, der Hochrechnung (prognose_platz, erw_punkte, p_achtelfinale, p_playoffs, p_aus)."""
    from fussballdb.model.cl_table import table

    rows = table(season)
    if not rows:
        raise ValueError(f"Keine Ligaphase für die CL-Saison {season}.")
    return {"season": season, "label": f"{season}/{(season + 1) % 100:02d}", "rows": rows}


@app.get("/cl/round/{season}/{round_no}")
def cl_round(season: int, round_no: int):
    """Spiele einer CL-Runde mit Prognose, Tipp und Tipp-Punkten. Bei gespielten Spielen zählt die
    Live-Prognose von vor dem Anpfiff, sonst die Rückblick-Prognose (Stand vor der Runde)."""
    games = _rows(
        f"""
        SELECT m.id, m.kickoff, m.round_name, m.neutral, ht.name AS home, at.name AS away,
               m.home_goals, m.away_goals, m.finished,
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
        WHERE m.competition = 'CL' AND m.season = :y AND m.round_no = :r
        ORDER BY m.kickoff, m.id
        """,
        y=season, r=round_no,
    )
    if not games:
        raise ValueError(f"Runde {round_no} der CL-Saison {season} gibt es nicht.")
    tv = tv_for("CL", [g["id"] for g in games])
    for g in games:
        g["explanation"] = json.loads(g["explanation"]) if g["explanation"] else []
        g["tv"] = tv.get(g["id"], {})
    scored = [g for g in games if g["points"] is not None]
    season_rows = _rows(
        f"""
        SELECT {POINTS_SQL} AS points
        FROM eu_match m
        LEFT JOIN LATERAL (
            SELECT * FROM eu_prediction x WHERE x.match_id = m.id
            ORDER BY (x.basis = 'live' AND x.as_of <= m.kickoff) DESC, (x.basis = 'rueckblick') DESC LIMIT 1
        ) p ON true
        WHERE m.competition = 'CL' AND m.season = :y AND m.round_no <= :r
        """,
        y=season, r=round_no,
    )
    season_scored = [r["points"] for r in season_rows if r["points"] is not None]

    def summary(points: list[int]) -> dict:
        return {"spiele": len(points), "punkte": sum(points), "tendenz": sum(1 for p in points if p > 0),
                "exakt": sum(1 for p in points if p == EXACT)}

    return {
        "season": season, "round_no": round_no, "round_name": games[0]["round_name"], "games": games,
        "summary": summary([g["points"] for g in scored]), "season_summary": summary(season_scored),
        "punkteregel": {"sieg_tendenz": WIN_TENDENCY, "sieg_tordifferenz": WIN_DIFF, "exakt": EXACT,
                        "remis_tendenz": DRAW_TENDENCY},
    }


@app.get("/kickbase/projections")
def kickbase_projections(matchdays: Annotated[int, Query(ge=1, le=10)] = 1):
    """Erwartete Ereignisse je Spieler für die nächsten Spieltage (Einsatz, Tore, Vorlagen, Zu null, Gelb)."""
    from fussballdb.features.kickbase_projection import projections

    df = projections(matchdays)
    return json.loads(df.to_json(orient="records", force_ascii=False)) if not df.empty else []


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


