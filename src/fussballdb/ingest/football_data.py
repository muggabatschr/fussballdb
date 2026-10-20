"""Spielstatistiken und Wettquoten von football-data.co.uk (D1 = 1. Bundesliga)."""

import csv
import io
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fussballdb.db.models import Match, MatchTeamStats, Odds, Season
from fussballdb.ingest.http import get_text
from fussballdb.ingest.team_mapping import TeamResolver
from fussballdb.ingest.upsert import upsert

# Buchmacher-Präfix in den Spalten -> Präfix der Over/Under-Spalten
BOOKMAKERS = {"B365": "B365", "PS": "P", "BFE": "BFE", "Avg": "Avg", "Max": "Max"}


def _num(row: dict, key: str, cast=float):
    value = (row.get(key) or "").strip()
    if not value:
        return None
    try:
        return cast(float(value)) if cast is int else cast(value)
    except ValueError:
        return None


def _odds_rows(row: dict, match_id: int) -> list[dict]:
    rows = []
    for book, ou in BOOKMAKERS.items():
        for closing in (False, True):
            c = "C" if closing else ""
            home = _num(row, f"{book}{c}H")
            if home is None:
                continue
            rows.append(
                {
                    "match_id": match_id,
                    "bookmaker": book,
                    "is_closing": closing,
                    "home": home,
                    "draw": _num(row, f"{book}{c}D"),
                    "away": _num(row, f"{book}{c}A"),
                    "over25": _num(row, f"{ou}{c}>2.5"),
                    "under25": _num(row, f"{ou}{c}<2.5"),
                }
            )
    return rows


def ingest_season(session: Session, start_year: int) -> tuple[int, list[str]]:
    season = session.scalar(select(Season).where(Season.start_year == start_year))
    if season is None:
        raise RuntimeError(f"Saison {start_year} fehlt. Zuerst OpenLigaDB importieren.")
    code = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
    text = get_text(f"https://www.football-data.co.uk/mmz4281/{code}/D1.csv")
    teams = TeamResolver(session)
    matches = {
        (m.home_team_id, m.away_team_id): m.id
        for m in session.scalars(select(Match).where(Match.season_id == season.id))
    }
    stats, odds, missing = [], [], []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        if not row.get("HomeTeam"):
            continue
        home_id = teams.resolve("football_data", row["HomeTeam"])
        away_id = teams.resolve("football_data", row["AwayTeam"])
        match_id = matches.get((home_id, away_id))
        if match_id is None:
            missing.append(f"{row['Date']} {row['HomeTeam']} - {row['AwayTeam']}")
            continue
        for team_id, is_home, p in ((home_id, True, "H"), (away_id, False, "A")):
            stats.append(
                {
                    "match_id": match_id,
                    "team_id": team_id,
                    "is_home": is_home,
                    "goals": _num(row, f"FT{p}G", int),
                    "xg_fd": _num(row, f"{p}xG"),
                    "shots": _num(row, f"{p}S", int),
                    "shots_on_target": _num(row, f"{p}ST", int),
                    "corners": _num(row, f"{p}C", int),
                    "fouls": _num(row, f"{p}F", int),
                    "yellow_cards": _num(row, f"{p}Y", int),
                    "red_cards": _num(row, f"{p}R", int),
                }
            )
        odds += _odds_rows(row, match_id)
    upsert(session, MatchTeamStats, stats, ["match_id", "team_id"])
    upsert(session, Odds, odds, ["match_id", "bookmaker", "is_closing"])
    return len(stats) // 2, missing


def ingest_fixture_odds(session: Session) -> tuple[int, int]:
    """Vorab-Quoten für die kommenden Spiele (fixtures.csv, wird vor jedem Spieltag befüllt).

    Liefert (Spiele mit Quoten, Bundesliga-Spiele ab heute in der Datei). Ist der zweite Wert 0, hat
    football-data den Spieltag noch nicht eingestellt; ist er größer als der erste, fehlt eine Zuordnung."""
    text = get_text("https://www.football-data.co.uk/fixtures.csv")
    teams = TeamResolver(session)
    open_matches = {
        (m.home_team_id, m.away_team_id): m.id
        for m in session.scalars(select(Match).where(Match.finished.is_(False)))
    }
    odds, listed = [], 0
    for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        if row.get("Div") != "D1":
            continue
        try:
            listed += datetime.strptime(row["Date"], "%d/%m/%Y").date() >= date.today()
        except (KeyError, ValueError):
            pass
        key = (teams.resolve("football_data", row["HomeTeam"]), teams.resolve("football_data", row["AwayTeam"]))
        if key in open_matches:
            odds += _odds_rows(row, open_matches[key])
    upsert(session, Odds, odds, ["match_id", "bookmaker", "is_closing"])
    return len({o["match_id"] for o in odds}), listed
