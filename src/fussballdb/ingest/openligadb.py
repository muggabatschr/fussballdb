"""Spielplan und Ergebnisse von OpenLigaDB. Legt die Spiele (match) an, auf die alle
anderen Quellen gemappt werden."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fussballdb.db.models import Match, Season
from fussballdb.ingest.http import get_json
from fussballdb.ingest.team_mapping import TeamResolver
from fussballdb.ingest.upsert import upsert


def ensure_season(session: Session, start_year: int) -> Season:
    season = session.scalar(select(Season).where(Season.start_year == start_year))
    if season is None:
        season = Season(start_year=start_year, label=f"{start_year}/{(start_year + 1) % 100:02d}")
        session.add(season)
        session.flush()
    return season


def _result(match: dict, type_id: int) -> tuple[int | None, int | None]:
    for r in match.get("matchResults") or []:
        if r["resultTypeID"] == type_id:
            return r["pointsTeam1"], r["pointsTeam2"]
    return None, None


def ingest_season(session: Session, start_year: int) -> int:
    season = ensure_season(session, start_year)
    teams = TeamResolver(session)
    data = get_json(f"https://api.openligadb.de/getmatchdata/bl1/{start_year}")
    rows = []
    for m in data:
        home, away = _result(m, 2)
        ht_home, ht_away = _result(m, 1)
        finished = bool(m["matchIsFinished"])
        rows.append(
            {
                "season_id": season.id,
                "matchday": m["group"]["groupOrderID"],
                "kickoff": datetime.fromisoformat(m["matchDateTimeUTC"].replace("Z", "+00:00")),
                "home_team_id": teams.resolve("openligadb", m["team1"]["teamName"]),
                "away_team_id": teams.resolve("openligadb", m["team2"]["teamName"]),
                "home_goals": home if finished else None,
                "away_goals": away if finished else None,
                "ht_home_goals": ht_home,
                "ht_away_goals": ht_away,
                "finished": finished,
                "openligadb_id": m["matchID"],
            }
        )
    upsert(session, Match, rows, ["season_id", "home_team_id", "away_team_id"])
    return len(rows)
