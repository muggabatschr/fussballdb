"""Ältere Bundesliga-Saisons (config.HISTORY_SEASONS, 1993/94 bis 2013/14) nur für die Anzeige:
Direktvergleich, Teamhistorie, SQL. Das Prognosemodell nutzt sie nicht (config.MODEL_FIRST_SEASON).

Die Spiele kommen aus der football-data-Datei. OpenLigaDB ist für diese Saisons lückenhaft (2002/03 nur
9 Spiele, 2003/04 ohne Ergebnisse) und liefert nur, wo vorhanden, Anstoßzeit und Spieltag. Sonst gilt
15:30 Uhr am Spieltag (die Datei hat nur das Datum) und der Spieltag aus der Reihenfolge der Spiele je
Team. Statistiken (Schüsse ab 2000/01, Ecken, Fouls, Karten) und Quoten liefert in allen
Saisons football-data. xG, Schüsse mit Position und Kader gibt es vor 2014/15 nicht."""

import csv
import io
from collections import Counter
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from fussballdb.db.models import Match
from fussballdb.ingest import football_data, openligadb
from fussballdb.ingest.http import get_json, get_text
from fussballdb.ingest.team_mapping import TeamResolver
from fussballdb.ingest.upsert import upsert

OPENLIGADB_FROM = 2002  # erste Saison mit Bundesliga-Spielplan bei OpenLigaDB
BERLIN = ZoneInfo("Europe/Berlin")


def _date(value: str):
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unbekanntes Datum {value!r}")


def _openligadb(teams: TeamResolver, start_year: int) -> dict[tuple[int, int], dict]:
    """(Heim, Gast) -> Anstoß, Spieltag und ID laut OpenLigaDB, soweit vorhanden."""
    if start_year < OPENLIGADB_FROM:
        return {}
    out = {}
    for m in get_json(f"https://api.openligadb.de/getmatchdata/bl1/{start_year}", cache=True):
        key = (teams.resolve("openligadb", m["team1"]["teamName"]), teams.resolve("openligadb", m["team2"]["teamName"]))
        out[key] = {"matchday": m["group"]["groupOrderID"], "openligadb_id": m["matchID"],
                    "kickoff": datetime.fromisoformat(m["matchDateTimeUTC"].replace("Z", "+00:00"))}
    return out


def ingest_season(session: Session, start_year: int) -> tuple[int, int, list[str]]:
    """(Spiele, Spiele mit Statistik/Quoten, nicht zugeordnete Zeilen) einer älteren Saison."""
    season = openligadb.ensure_season(session, start_year)
    code = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
    text = get_text(f"https://www.football-data.co.uk/mmz4281/{code}/D1.csv", cache=True)
    teams = TeamResolver(session)
    oldb = _openligadb(teams, start_year)
    rows = [r for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))) if r.get("HomeTeam")]
    rows.sort(key=lambda r: _date(r["Date"]))
    played: Counter[int] = Counter()
    out = []
    for r in rows:
        home = teams.resolve("football_data", r["HomeTeam"])
        away = teams.resolve("football_data", r["AwayTeam"])
        # Spieltag = nächstes Spiel des Teams mit den meisten bisherigen Spielen (Nachholspiele verschieben das leicht)
        matchday = min(max(played[home], played[away]) + 1, 34)
        played[home] += 1
        played[away] += 1
        ht = (football_data._num(r, "HTHG", int), football_data._num(r, "HTAG", int))
        known = oldb.get((home, away), {})
        out.append({
            "season_id": season.id,
            "matchday": known.get("matchday", matchday),
            "kickoff": known.get("kickoff") or datetime.combine(_date(r["Date"]), time(15, 30), tzinfo=BERLIN),
            "openligadb_id": known.get("openligadb_id"),
            "home_team_id": home,
            "away_team_id": away,
            "home_goals": int(r["FTHG"]),
            "away_goals": int(r["FTAG"]),
            "ht_home_goals": ht[0],
            "ht_away_goals": ht[1],
            "finished": True,
        })
    upsert(session, Match, out, ["season_id", "home_team_id", "away_team_id"])
    session.flush()
    n_stats, missing = football_data.ingest_season(session, start_year)
    return len(out), n_stats, missing
