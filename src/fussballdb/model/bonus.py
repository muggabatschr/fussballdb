"""Prognosen für Kicktipp-Bonusfragen (Extratipps).

Bonusfragen werden vor dem ersten Spieltag getippt. Die Hauptprognose nutzt deshalb nur das Wissen zum
Tippschluss der Frage: Modell mit allen Spielen, Kaderwerten und gemeldeten Verletzten bis dahin trainiert,
jedes Saisonspiel damit vorhergesagt und die Saison 10.000-mal von vorn durchgespielt (Spiele, die vor dem
Tippschluss schon gespielt waren, zählen mit ihrem Ergebnis). Daneben steht zum Vergleich der Stand heute
(model/season_sim.py mit den Live-Prognosen).

Erkannt werden Fragen nach Meister, Herbstmeister (nach dem 17. Spieltag), Plätzen 16–18, Absteigern und
Platz 1–4, dazu das Team des Torschützenkönigs (top_scorer: Torraten je Spieler, Saison ausgespielt; zum
Tippschluss ohne Neuzugänge, die noch nicht in der Bundesliga gespielt haben). Der erste Trainerwechsel ist
eine Näherung: Daten zu Trainern gibt es nicht, erste Entlassungen folgen aber meist auf einen schlechten
Start; gezeigt wird, wer nach dem 8. Spieltag am wahrscheinlichsten auf Platz 16–18 steht."""

import re
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from fussballdb.model.season_sim import simulate, simulate_games

HALF_SEASON = 17
EARLY_START = 8  # bis hierhin fallen die meisten ersten Trainerentlassungen
BERLIN = ZoneInfo("Europe/Berlin")

# Frage -> (Spalte der Simulation, Anzahl Antworten, simulieren bis Spieltag (None = Saisonende), Hinweis)
SCORER = re.compile(r"meisten tore|torschützenkönig|torjäger|torschütze")
KINDS = [
    (re.compile(r"herbstmeister"), ("p_meister", 3, HALF_SEASON, None)),
    (re.compile(r"trainer"), ("p_16_18", 4, EARLY_START,
                              "Näherung: wer nach dem 8. Spieltag am wahrscheinlichsten auf Platz 16–18 steht")),
    (re.compile(r"meister"), ("p_meister", 3, None, None)),
    (re.compile(r"16\s*-\s*18|plätze 16"), ("p_16_18", 5, None, None)),
    (re.compile(r"abst"), ("p_abstieg", 4, None, None)),
    (re.compile(r"1\s*-\s*4|champions league"), ("p_top4", 6, None, None)),
]


@lru_cache(maxsize=4)
def _deadline_games(season: int, cutoff: datetime) -> pd.DataFrame:
    """Alle Spiele der Saison mit dem Wissensstand zu `cutoff`: vorher gespielte mit Ergebnis (known), die übrigen
    mit Prognose (p_home, p_draw, p_away, eh, ea) aus einem Modell, das nur Daten bis `cutoff` kennt."""
    from fussballdb.features import euro_load
    from fussballdb.features.availability import AvailabilityModel
    from fussballdb.model.data import load_matches, load_squad_values
    from fussballdb.model.ensemble import Forecaster
    from fussballdb.model.evaluate import load_injuries

    df = load_matches()
    cut = pd.Timestamp(cutoff)
    games = df[df["season"] == season].copy()
    if games.empty:
        return games
    games["known"] = games["finished"] & (games["kickoff"] < cut)
    model = Forecaster(values=load_squad_values()).fit(df, cut)
    availability, injuries, schedule = AvailabilityModel(), load_injuries(), euro_load.euro_schedule()
    preds = {}
    for r in games[~games["known"]].itertuples():
        impacts = []
        for team in (r.home_id, r.away_id):
            suspended = availability.suspended_as_of(team, cut)
            missing = availability.injured_as_of(team, cut, injuries) | suspended
            impacts.append(euro_load.apply(availability.impact(team, cut, missing, suspended), team, r.kickoff, schedule))
        p = model.predict_match(r.home_id, r.away_id, r.match_id, *impacts)
        preds[r.match_id] = (p["p_home"], p["p_draw"], p["p_away"], p["exp_home_goals"], p["exp_away_goals"])
    cols = ["p_home", "p_draw", "p_away", "eh", "ea"]
    games[cols] = pd.DataFrame([preds.get(m, (None,) * 5) for m in games["match_id"]], index=games.index, columns=cols)
    return games


@lru_cache(maxsize=8)
def deadline_table(season: int, cutoff: datetime, until: int | None) -> pd.DataFrame:
    """Simulation der Tabelle mit dem Wissensstand zum Zeitpunkt `cutoff` (wie die Rückblick-Prognosen)."""
    games = _deadline_games(season, cutoff)
    if until and not games.empty:
        games = games[games["matchday"] <= until]
    if games.empty:
        return pd.DataFrame()
    played = games[games["known"]][["home", "away", "hg", "ag"]]
    return simulate_games(played, games[~games["known"]][["home", "away", "p_home", "p_draw", "p_away", "eh", "ea"]])


TOP_SCORER_SIMS = 10_000
RATE_SPREAD = 8.0  # Gamma-Form der Streuung der Torrate je Durchlauf (Verletzung, Form, Rotation): rund ±35 %


def top_scorer(season: int, cutoff: datetime | None = None, n: int = TOP_SCORER_SIMS, seed: int = 0) -> dict:
    """Wer stellt am Saisonende den Spieler mit den meisten Toren? Je Spieler: Tore bis zum Stichtag (ohne
    cutoff: bis heute) plus erwartete Tore in jedem übrigen Spiel (xG pro 90, zum Positionsschnitt geglättet, mal
    erwartete Minuten, skaliert mit der Torerwartung seines Teams gegen diesen Gegner), dann n-mal ausgespielt.
    Die Torrate ist je zur Hälfte xG und echte Tore pro 90 Minuten (beide zum Positionsschnitt geglättet), weil
    Torjäger dauerhaft öfter treffen als ihr xG; je Durchlauf streut sie (Gamma, rund ±35 %), dann Poisson. Bei Gleichstand zählt jedes beteiligte Team. Liefert {"teams": [{team, p}], "spieler": [{name,
    team, tore, erwartet, p}]}, p in Prozent. Zum Stichtag kennt das Modell keine Neuzugänge ohne Bundesliga-
    Vergangenheit und ordnet Wechsel innerhalb der Liga noch dem alten Verein zu."""
    from sqlalchemy import text

    from fussballdb.db.session import engine
    from fussballdb.features.kickbase_projection import PRIOR_MINUTES, WINDOW_DAYS, _player_table

    cut = pd.Timestamp(cutoff) if cutoff else pd.Timestamp.now(tz="UTC")
    apps = pd.read_sql(text("""
        SELECT pm.match_id, pm.player_id, p.name, pm.team_id, pm.position, pm.started, pm.minutes,
               pm.xg, pm.xa, pm.goals, pm.assists, pm.yellow_cards, pm.red_cards, m.kickoff, s.start_year AS season
        FROM player_match pm JOIN match m ON m.id = pm.match_id JOIN player p ON p.id = pm.player_id
        JOIN season s ON s.id = m.season_id
        WHERE m.kickoff < :c AND m.kickoff > :c - make_interval(days => :d)"""), engine,
        params={"c": cut.to_pydatetime(), "d": WINDOW_DAYS})
    if apps.empty:
        return {"teams": [], "spieler": []}
    apps["kickoff"] = pd.to_datetime(apps["kickoff"], utc=True)
    players = _player_table(apps)
    pos_goals = players.groupby("position").apply(lambda g: g["goals"].sum() / max(g["minutes"].sum(), 1))
    goals90 = (players["goals"] + players["position"].map(pos_goals) * PRIOR_MINUTES) / (players["minutes"] + PRIOR_MINUTES) * 90
    players["rate90"] = (players["xg90"] + goals90) / 2
    goals_so_far = apps[apps["season"] == season].groupby("player_id")["goals"].sum()
    players["tore"] = goals_so_far.reindex(players.index).fillna(0).astype(int)

    if cutoff:
        games = _deadline_games(season, cutoff)
        games = games[~games["known"]]
        fixtures = games.rename(columns={"home_id": "home_team_id", "away_id": "away_team_id",
                                         "eh": "exp_home_goals", "ea": "exp_away_goals"})
    else:
        fixtures = pd.read_sql(text("""
            SELECT m.home_team_id, m.away_team_id, p.exp_home_goals, p.exp_away_goals
            FROM match m JOIN season s ON s.id = m.season_id
            LEFT JOIN prediction p ON p.match_id = m.id AND p.basis = 'live'
            WHERE s.start_year = :y AND NOT m.finished"""), engine, params={"y": season})
    # Torerwartung je Team im Schnitt der letzten Spiele, um die Torerwartung je Spiel darauf zu beziehen
    team_xg = apps.groupby(["team_id", "match_id"])["xg"].sum().groupby("team_id").mean()
    # Einsatz über die ganze Saison: Startelf- und Einwechselquote über alle Spiele des Teams im Zeitfenster
    # (die letzten 5 Spiele wie bei Kickbase wären hier zu kurz, z. B. Rotation am Saisonende)
    own = apps[apps["team_id"] == apps["player_id"].map(players["team_id"])]
    # nur Spiele des Teams ab dem ersten Einsatz des Spielers dort (Neuzugänge sonst unterschätzt)
    team_kickoffs = apps.drop_duplicates("match_id").groupby("team_id")["kickoff"].apply(lambda s: np.sort(s.to_numpy()))
    first = own.groupby("player_id")["kickoff"].min().reindex(players.index)
    n_games = pd.Series([max(int((team_kickoffs[tm] >= f).sum()), 1) if pd.notna(f) else 1
                         for tm, f in zip(players["team_id"], first)], index=players.index)
    starts = own[own["started"]].groupby("player_id")["match_id"].nunique().reindex(players.index).fillna(0)
    subs = own[~own["started"]].groupby("player_id")["match_id"].nunique().reindex(players.index).fillna(0)
    minutes = (starts / n_games).clip(upper=1) * 85 + (subs / n_games).clip(upper=1) * players["sub_minutes"]
    expected = pd.Series(0.0, index=players.index)
    for side, goals in (("home_team_id", "exp_home_goals"), ("away_team_id", "exp_away_goals")):
        per_team = fixtures.groupby(side)[goals].apply(lambda s: s.fillna(s.mean()).sum())
        scale = (per_team / team_xg.reindex(per_team.index)).fillna(0)  # Summe der Spiel-Faktoren je Team
        expected += players["team_id"].map(scale).fillna(0) * players["rate90"] * minutes / 90
    rng = np.random.default_rng(seed)
    spread = rng.gamma(RATE_SPREAD, 1 / RATE_SPREAD, size=(n, len(players)))
    final = players["tore"].to_numpy() + rng.poisson(expected.to_numpy() * spread)
    best = final == final.max(axis=1, keepdims=True)
    p_player = best.mean(axis=0)
    team_ids = players["team_id"].to_numpy()
    names = dict(pd.read_sql(text("SELECT id, name FROM team"), engine).itertuples(index=False, name=None))
    teams = {t: float(best[:, team_ids == t].any(axis=1).mean()) for t in np.unique(team_ids)}
    top_teams = sorted(teams.items(), key=lambda x: -x[1])
    order = np.argsort(-p_player)[:8]
    return {"teams": [{"team": names[int(t)], "p": round(100 * p, 1)} for t, p in top_teams if p > 0],
            "spieler": [{"name": players["name"].iloc[i], "team": names[int(team_ids[i])],
                         "tore": int(players["tore"].iloc[i]), "erwartet": round(float(players["tore"].iloc[i] + expected.iloc[i]), 1),
                         "p": round(100 * float(p_player[i]), 1)} for i in order if p_player[i] > 0]}


def _top(sim: pd.DataFrame, col: str, n: int) -> list[dict] | None:
    if sim.empty:
        return None
    rows = sim.sort_values(col, ascending=False).head(n)
    return [{"team": r["name"], "p": float(r[col])} for _, r in rows.iterrows() if r[col] > 0]


def _deadline(termin: str) -> datetime | None:
    try:
        return datetime.strptime(termin, "%d.%m.%y %H:%M").replace(tzinfo=BERLIN)
    except (TypeError, ValueError):
        return None


def _scorer_item(q: dict, season: int) -> dict:
    """Bonusfrage nach dem Team des Torschützenkönigs (oder dem Spieler selbst)."""
    cutoff = _deadline(q.get("termin", ""))
    at_deadline = top_scorer(season, cutoff) if cutoff else None
    now = None if q.get("antworten") else top_scorer(season)
    fav = (at_deadline or now or {}).get("spieler") or []
    hint = ("Favorit zum Tippschluss: " if at_deadline else "Favorit: ") + ", ".join(
        f"{s['name']} ({s['team']}) {s['p']:.0f} %" for s in fav[:3]) if fav else None
    if at_deadline:
        hint += " · zum Tippschluss ohne Neuzugänge, die noch nicht in der Bundesliga gespielt hatten"
    return {**q, "prognose": at_deadline["teams"][:5] if at_deadline else None,
            "heute": now["teams"][:5] if now else None,
            "stichtag": cutoff.isoformat(timespec="minutes") if cutoff else None, "hinweis": hint}


def forecasts(questions: list[dict], season: int) -> list[dict]:
    """Je Frage: `prognose` (Wissen zum Tippschluss), `heute` (aktueller Stand) oder ein `hinweis`."""
    today: dict[int | None, pd.DataFrame] = {}
    out = []
    for q in questions:
        text = q["frage"].lower()
        if SCORER.search(text):
            out.append(_scorer_item(q, season))
            continue
        kind = next((k for pattern, k in KINDS if pattern.search(text)), None)
        item = {**q, "prognose": None, "heute": None, "stichtag": None,
                "hinweis": kind[3] if kind else "keine Prognose möglich (dafür fehlen Daten)"}
        if kind:
            col, n, until, _ = kind
            cutoff = _deadline(q.get("termin", ""))
            if cutoff:
                item["prognose"] = _top(deadline_table(season, cutoff, until), col, n)
                item["stichtag"] = cutoff.isoformat(timespec="minutes")
            if not q.get("antworten"):  # entschieden: der Stand heute ist dann ohne Aussage
                if until not in today:
                    today[until] = simulate(season, until_matchday=until)
                item["heute"] = _top(today[until], col, n)
        out.append(item)
    return out
