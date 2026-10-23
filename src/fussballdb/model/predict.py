"""Prognosen für kommende Spiele berechnen und in der Tabelle prediction speichern."""

import json

import numpy as np
import pandas as pd
from sqlalchemy import select, text

from fussballdb.db.models import EloRating, PlayerAbsence, Prediction
from fussballdb.db.session import engine, session_scope
from fussballdb.features import euro_load
from fussballdb.features.availability import AvailabilityModel
from fussballdb.ingest.upsert import upsert
from fussballdb.model.data import load_matches
from fussballdb.model.ensemble import MODEL_VERSION, Forecaster
from fussballdb.model.explain import explain


def active_absences() -> dict[int, set[int]]:
    """Aktuelle Ausfälle (Verletzte und Gesperrte) je Team; Gesperrte zusätzlich unter (team_id, "gesperrt")."""
    with session_scope() as s:
        rows = s.execute(
            select(PlayerAbsence.team_id, PlayerAbsence.player_id, PlayerAbsence.kind).where(
                PlayerAbsence.active, PlayerAbsence.player_id.is_not(None)
            )
        ).all()
    out: dict = {}
    for team_id, pid, kind in rows:
        out.setdefault(team_id, set()).add(pid)
        if kind == "suspension":
            out.setdefault((team_id, "gesperrt"), set()).add(pid)
    return out


def build_forecaster() -> tuple[Forecaster, pd.DataFrame]:
    df = load_matches()
    now = pd.Timestamp.now(tz="UTC")
    return Forecaster().fit(df, now), df


def store_elo(model: Forecaster, df: pd.DataFrame) -> None:
    """Elo vor/nach jedem beendeten Spiel in elo_rating ablegen."""
    elo = model.elo_table.join(df.set_index("match_id")[["kickoff", "home_id", "away_id"]])
    elo = elo[elo["elo_home_after"].notna()]
    rows = []
    for mid, r in elo.iterrows():
        rows.append({"match_id": int(mid), "team_id": int(r.home_id), "played_at": r.kickoff,
                     "elo_before": float(r.elo_home), "elo_after": float(r.elo_home_after)})
        rows.append({"match_id": int(mid), "team_id": int(r.away_id), "played_at": r.kickoff,
                     "elo_before": float(r.elo_away), "elo_after": float(r.elo_away_after)})
    with session_scope() as s:
        upsert(s, EloRating, rows, ["match_id", "team_id"])


def predict_pair(home_id: int, away_id: int, match_id: int | None = None,
                 model: Forecaster | None = None, availability: AvailabilityModel | None = None,
                 absences: dict[int, set[int]] | None = None, kickoff: pd.Timestamp | None = None,
                 schedule: dict | None = None) -> dict:
    """Prognose für ein Spiel inkl. Korrektur um die aktuelle Verletztenliste (β = 0,5) und, mit `kickoff`,
    um die Europapokal-Belastung (features/euro_load.py)."""
    if model is None:
        model, _ = build_forecaster()
    availability = availability or AvailabilityModel()
    absences = absences if absences is not None else active_absences()
    now = pd.Timestamp.now(tz="UTC")
    hi = availability.impact(home_id, now, absences.get(home_id, set()), absences.get((home_id, "gesperrt")))
    ai = availability.impact(away_id, now, absences.get(away_id, set()), absences.get((away_id, "gesperrt")))
    if kickoff is not None:
        schedule = schedule if schedule is not None else euro_load.euro_schedule()
        hi = euro_load.apply(hi, home_id, kickoff, schedule)
        ai = euro_load.apply(ai, away_id, kickoff, schedule)
    out = model.predict_match(home_id, away_id, match_id, hi, ai)
    out["absences"] = {"home": hi, "away": ai}
    return out


PRED_FIELDS = ("p_home", "p_draw", "p_away", "exp_home_goals", "exp_away_goals", "p_over25", "p_btts")


def market_probs() -> dict[int, tuple[float, float, float]]:
    """Eröffnungsquoten (Durchschnitt) ohne Marge je Spiel; vor dem Anpfiff bekannt."""
    from fussballdb.model.data import load_market

    m = load_market()
    m = m[~m["is_closing"]]
    return {int(r.match_id): (r.p_home, r.p_draw, r.p_away) for r in m.itertuples()}


SCORE_GOALS = 10  # gespeicherte Ergebnisse 0:0 bis 9:9


def score_json(matrix: np.ndarray) -> str:
    return json.dumps(np.round(matrix[:SCORE_GOALS, :SCORE_GOALS], 5).tolist())


def _row(match_id: int, p: dict, as_of: pd.Timestamp, basis: str, home: str = "", away: str = "",
         market: tuple[float, float, float] | None = None) -> dict:
    return {
        "explanation": json.dumps(explain(p, home, away, market), ensure_ascii=False) if home else None,
        "match_id": int(match_id), "model_version": MODEL_VERSION, **{k: float(p[k]) for k in PRED_FIELDS},
        "as_of": as_of, "basis": basis, "tip_home": p["tip"][0], "tip_away": p["tip"][1],
        "score_probs": score_json(p["score_probs"]) if "score_probs" in p else None,
        # "" statt None, damit ein Update eine leere Ausfallliste auch wirklich speichert
        "missing_home": ", ".join(p["absences"]["home"]["missing_regulars"])[:400],
        "missing_away": ", ".join(p["absences"]["away"]["missing_regulars"])[:400],
    }


def predict_upcoming(matchdays: int | None = None) -> pd.DataFrame:
    """Live-Prognosen für die offenen Spiele der laufenden Saison (Standard: alle restlichen Spieltage)
    mit dem heutigen Datenstand. Wird bis zum Anpfiff bei jedem Update überschrieben, danach nie mehr."""
    model, df = build_forecaster()
    store_elo(model, df)
    upcoming = df[~df["finished"]].sort_values("kickoff")
    if upcoming.empty:
        return pd.DataFrame()
    season = upcoming["season"].iloc[0]
    first_md = upcoming["matchday"].iloc[0]
    upcoming = upcoming[upcoming["season"] == season]
    if matchdays:
        upcoming = upcoming[upcoming["matchday"] < first_md + matchdays]
    availability = AvailabilityModel()
    absences = active_absences()
    markets = market_probs()
    schedule = euro_load.euro_schedule()
    now = pd.Timestamp.now(tz="UTC")
    rows, out = [], []
    for r in upcoming.itertuples():
        p = predict_pair(r.home_id, r.away_id, r.match_id, model, availability, absences, r.kickoff, schedule)
        rows.append(_row(r.match_id, p, now, "live", r.home, r.away, markets.get(r.match_id)))
        out.append({"spieltag": r.matchday, "anstoss": r.kickoff, "heim": r.home, "gast": r.away, **rows[-1],
                    "ausfaelle_heim": rows[-1]["missing_home"], "ausfaelle_gast": rows[-1]["missing_away"]})
    with session_scope() as s:
        upsert(s, Prediction, rows, ["match_id", "model_version"])
        s.execute(text("UPDATE prediction SET created_at = now() WHERE match_id = ANY(:ids)"),
                  {"ids": [r["match_id"] for r in rows]})
    return pd.DataFrame(out)


def backfill(seasons: list[int] | None = None, force: bool = False, progress=None) -> int:
    """Rückblick-Prognosen für gespielte Spieltage, die noch keine Prognose haben.

    Pro Spieltag wird nur verwendet, was vor dem Anpfiff des ersten Spiels bekannt war: Modell und Elo
    werden mit den Spielen davor trainiert. Als Ausfälle zählen Spieler, die am Stichtag laut
    Transfermarkt-Verletzungshistorie verletzt gemeldet waren (ab 2023/24), und Sperren aus den Karten
    des letzten Spiels (Rot/Gelb-Rot, 5./10./15. Gelbe; seit 2014/15). Live-Prognosen bleiben unberührt."""
    df = load_matches()
    with engine.connect() as conn:
        existing = {r[0] for r in conn.execute(
            text("SELECT match_id FROM prediction WHERE model_version = :v"), {"v": MODEL_VERSION})}
        if force:
            existing = {r[0] for r in conn.execute(text(
                "SELECT match_id FROM prediction WHERE model_version = :v AND basis = 'live'"), {"v": MODEL_VERSION})}
    played = df[df["finished"]]
    if seasons:
        played = played[played["season"].isin(seasons)]
    from fussballdb.model.data import load_squad_values

    from fussballdb.model.evaluate import load_injuries

    values = load_squad_values()
    injuries = load_injuries()
    availability = AvailabilityModel()
    markets = market_probs()
    schedule = euro_load.euro_schedule()
    total = 0
    for (season, md), games in played.groupby(["season", "matchday"], sort=True):
        todo = games[~games["match_id"].isin(existing)]
        if todo.empty:
            continue
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        if not (df["finished"] & (df["kickoff"] < cutoff)).any():
            continue  # allererster Spieltag ohne Vordaten
        model = Forecaster(values=values).fit(df, cutoff)
        rows = []
        for r in todo.itertuples():
            impacts = []
            for team in (r.home_id, r.away_id):
                suspended = availability.suspended_as_of(team, cutoff)
                missing = availability.injured_as_of(team, cutoff, injuries) | suspended
                impacts.append(euro_load.apply(availability.impact(team, cutoff, missing, suspended),
                                               team, r.kickoff, schedule))
            hi, ai = impacts
            p = model.predict_match(r.home_id, r.away_id, r.match_id, hi, ai)
            p["absences"] = {"home": hi, "away": ai}
            rows.append(_row(r.match_id, p, cutoff, "rueckblick", r.home, r.away, markets.get(r.match_id)))
        with session_scope() as s:
            upsert(s, Prediction, rows, ["match_id", "model_version"])
        total += len(rows)
        if progress:
            progress(season, md, len(rows))
    return total


def fill_score_probs(progress=None) -> int:
    """Ergebnis-Wahrscheinlichkeiten für gespeicherte Prognosen ohne score_probs nachtragen (Rückblick wie in
    backfill: je Spieltag nur Daten vor dem Anpfiff). Nur diese Spalte wird geschrieben, ausgerichtet an den
    gespeicherten 1/X/2-Wahrscheinlichkeiten; Tipps, Punkte und Begründungen bleiben, wie sie sind."""
    from fussballdb.model.data import load_squad_values
    from fussballdb.model.ensemble import aligned_matrix
    from fussballdb.model.evaluate import load_injuries

    df = load_matches()
    with engine.connect() as conn:
        stored = {r.match_id: r for r in conn.execute(text(
            "SELECT match_id, p_home, p_draw, p_away FROM prediction WHERE model_version = :v AND score_probs IS NULL"),
            {"v": MODEL_VERSION})}
    todo = df[df["match_id"].isin(stored)]
    values, injuries = load_squad_values(), load_injuries()
    availability = AvailabilityModel()
    schedule = euro_load.euro_schedule()
    total = 0
    for (season, md), games in todo.groupby(["season", "matchday"], sort=True):
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        if not (df["finished"] & (df["kickoff"] < cutoff)).any():
            continue
        model = Forecaster(values=values).fit(df, cutoff)
        updates = []
        for r in games.itertuples():
            impacts = []
            for team in (r.home_id, r.away_id):
                suspended = availability.suspended_as_of(team, cutoff)
                missing = availability.injured_as_of(team, cutoff, injuries) | suspended
                impacts.append(euro_load.apply(availability.impact(team, cutoff, missing, suspended),
                                               team, r.kickoff, schedule))
            p = model.predict_match(r.home_id, r.away_id, r.match_id, *impacts)
            s = stored[r.match_id]
            probs = {"p_home": s.p_home, "p_draw": s.p_draw, "p_away": s.p_away}
            updates.append({"m": int(r.match_id), "s": score_json(aligned_matrix(p["score_probs"], probs)),
                            "v": MODEL_VERSION})
        with engine.begin() as conn:
            conn.execute(text("UPDATE prediction SET score_probs = :s WHERE match_id = :m AND model_version = :v"),
                         updates)
        total += len(updates)
        if progress:
            progress(season, md, len(updates))
    return total


def evaluate_stored() -> pd.DataFrame:
    """Gespeicherte Prognosen gegen die inzwischen bekannten Ergebnisse."""
    return pd.read_sql(
        text(
            """
            SELECT p.model_version, count(*) AS spiele,
                   avg(power(p.p_home - (m.home_goals > m.away_goals)::int, 2)
                     + power(p.p_draw - (m.home_goals = m.away_goals)::int, 2)
                     + power(p.p_away - (m.home_goals < m.away_goals)::int, 2)) AS brier
            FROM prediction p JOIN match m ON m.id = p.match_id
            WHERE m.finished GROUP BY 1
            """
        ),
        engine,
    )
