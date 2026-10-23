"""Prognosen für Kicktipp-Bonusfragen (Extratipps).

Bonusfragen werden vor dem ersten Spieltag getippt. Die Hauptprognose nutzt deshalb nur das Wissen zum
Tippschluss der Frage: Modell mit allen Spielen, Kaderwerten und gemeldeten Verletzten bis dahin trainiert,
jedes Saisonspiel damit vorhergesagt und die Saison 10.000-mal von vorn durchgespielt (Spiele, die vor dem
Tippschluss schon gespielt waren, zählen mit ihrem Ergebnis). Daneben steht zum Vergleich der Stand heute
(model/season_sim.py mit den Live-Prognosen).

Erkannt werden Fragen nach Meister, Herbstmeister (nach dem 17. Spieltag), Plätzen 16–18, Absteigern und
Platz 1–4. Der erste Trainerwechsel ist eine Näherung: Daten zu Trainern gibt es nicht, erste Entlassungen
folgen aber meist auf einen schlechten Start; gezeigt wird, wer nach dem 8. Spieltag am wahrscheinlichsten auf
Platz 16–18 steht. Für den Torschützenkönig gibt es keine Prognose: dafür wären die Transfers vor der Saison
nötig, die das Modell zum Tippschluss nicht kennt."""

import re
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

from fussballdb.model.season_sim import simulate, simulate_games

HALF_SEASON = 17
EARLY_START = 8  # bis hierhin fallen die meisten ersten Trainerentlassungen
BERLIN = ZoneInfo("Europe/Berlin")

# Frage -> (Spalte der Simulation, Anzahl Antworten, simulieren bis Spieltag (None = Saisonende), Hinweis)
KINDS = [
    (re.compile(r"herbstmeister"), ("p_meister", 3, HALF_SEASON, None)),
    (re.compile(r"trainer"), ("p_16_18", 4, EARLY_START,
                              "Näherung: wer nach dem 8. Spieltag am wahrscheinlichsten auf Platz 16–18 steht")),
    (re.compile(r"meister"), ("p_meister", 3, None, None)),
    (re.compile(r"16\s*-\s*18|plätze 16"), ("p_16_18", 5, None, None)),
    (re.compile(r"abst"), ("p_abstieg", 4, None, None)),
    (re.compile(r"1\s*-\s*4|champions league"), ("p_top4", 6, None, None)),
]


@lru_cache(maxsize=8)
def deadline_table(season: int, cutoff: datetime, until: int | None) -> pd.DataFrame:
    """Simulation mit dem Wissensstand zum Zeitpunkt `cutoff` (wie die Rückblick-Prognosen)."""
    from fussballdb.features import euro_load
    from fussballdb.features.availability import AvailabilityModel
    from fussballdb.model.data import load_matches, load_squad_values
    from fussballdb.model.ensemble import Forecaster
    from fussballdb.model.evaluate import load_injuries

    df = load_matches()
    cut = pd.Timestamp(cutoff)
    games = df[df["season"] == season]
    if until:
        games = games[games["matchday"] <= until]
    if games.empty:
        return pd.DataFrame()
    known = games["finished"] & (games["kickoff"] < cut)
    played = games[known].rename(columns={"hg": "hg", "ag": "ag"})[["home", "away", "hg", "ag"]]
    model = Forecaster(values=load_squad_values()).fit(df, cut)
    availability, injuries, schedule = AvailabilityModel(), load_injuries(), euro_load.euro_schedule()
    rows = []
    for r in games[~known].itertuples():
        impacts = []
        for team in (r.home_id, r.away_id):
            suspended = availability.suspended_as_of(team, cut)
            missing = availability.injured_as_of(team, cut, injuries) | suspended
            impacts.append(euro_load.apply(availability.impact(team, cut, missing, suspended), team, r.kickoff, schedule))
        p = model.predict_match(r.home_id, r.away_id, r.match_id, *impacts)
        rows.append({"home": r.home, "away": r.away, "p_home": p["p_home"], "p_draw": p["p_draw"],
                     "p_away": p["p_away"], "eh": p["exp_home_goals"], "ea": p["exp_away_goals"]})
    return simulate_games(played, pd.DataFrame(rows))


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


def forecasts(questions: list[dict], season: int) -> list[dict]:
    """Je Frage: `prognose` (Wissen zum Tippschluss), `heute` (aktueller Stand) oder ein `hinweis`."""
    today: dict[int | None, pd.DataFrame] = {}
    out = []
    for q in questions:
        text = q["frage"].lower()
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
