"""xG, PPDA, Deep-Completions und alle Schüsse von understat.com."""

import html



from sqlalchemy import select
from sqlalchemy.orm import Session

from fussballdb.db.models import Match, MatchTeamStats, Player, PlayerMatch, Season, Shot
from fussballdb.ingest.http import get_json
from fussballdb.ingest.team_mapping import TeamResolver
from fussballdb.ingest.upsert import upsert

BASE = "https://understat.com"
AJAX = {"X-Requested-With": "XMLHttpRequest"}
BIG_CHANCE_XG = 0.3


def _ppda(value: dict) -> float | None:
    return round(value["att"] / value["def"], 2) if value and value.get("def") else None


def ingest_season(session: Session, start_year: int, with_shots: bool = True) -> tuple[int, list[str]]:
    season = session.scalar(select(Season).where(Season.start_year == start_year))
    if season is None:
        raise RuntimeError(f"Saison {start_year} fehlt. Zuerst OpenLigaDB importieren.")
    teams = TeamResolver(session)
    data = get_json(f"{BASE}/getLeagueData/Bundesliga/{start_year}", headers=AJAX)
    matches = {
        (m.home_team_id, m.away_team_id): m
        for m in session.scalars(select(Match).where(Match.season_id == season.id))
    }

    # Team-Historie: pro Team und Spiel xG, npxG, PPDA, deep, xPts (Schlüssel: Team + Anstoß)
    history: dict[tuple[int, str], dict] = {}
    for t in data["teams"].values():
        team_id = teams.resolve("understat", t["title"])
        for h in t["history"]:
            history[(team_id, h["date"])] = h

    stats, missing, done = [], [], 0
    for d in data["dates"]:
        if not d["isResult"]:
            continue
        home_id = teams.resolve("understat", d["h"]["title"])
        away_id = teams.resolve("understat", d["a"]["title"])
        match = matches.get((home_id, away_id))
        if match is None:
            missing.append(f"{d['datetime']} {d['h']['title']} - {d['a']['title']}")
            continue
        match.understat_id = int(d["id"])
        shots = []
        if with_shots:
            # beendete Spiele ändern sich nicht mehr -> dauerhaft cachen
            md = get_json(f"{BASE}/getMatchData/{d['id']}", headers=AJAX, cache=True, delay=0.4)
            shots = [s for side in ("h", "a") for s in md["shots"][side]]
            upsert(
                session,
                Shot,
                [
                    {
                        "id": int(s["id"]),
                        "match_id": match.id,
                        "team_id": home_id if s["h_a"] == "h" else away_id,
                        "player": html.unescape(s["player"]),
                        "player_assisted": html.unescape(s["player_assisted"]) if s["player_assisted"] else None,
                        "minute": int(s["minute"]),
                        "xg": float(s["xG"]),
                        "result": s["result"],
                        "situation": s["situation"],
                        "shot_type": s["shotType"],
                        "last_action": s["lastAction"],
                        "x": float(s["X"]),
                        "y": float(s["Y"]),
                    }
                    for s in shots
                ],
                ["id"],
            )
            players, appearances = _roster_rows(md.get("rosters") or {}, match.id, home_id, away_id)
            upsert(session, Player, players, ["id"])
            upsert(session, PlayerMatch, appearances, ["match_id", "player_id"])
        for team_id, side in ((home_id, "h"), (away_id, "a")):
            h = history.get((team_id, d["datetime"]), {})
            row = {
                "match_id": match.id,
                "team_id": team_id,
                "is_home": side == "h",
                "goals": int(d["goals"][side]),
                "xg": round(float(d["xG"][side]), 3),
                "npxg": round(h["npxG"], 3) if h else None,
                "xpts": round(h["xpts"], 3) if h else None,
                "ppda": _ppda(h.get("ppda")) if h else None,
                "deep": h.get("deep") if h else None,
            }
            if shots:
                row["big_chances"] = sum(
                    1 for s in shots if s["h_a"] == side and float(s["xG"]) >= BIG_CHANCE_XG
                )
            stats.append(row)
        done += 1
    upsert(session, MatchTeamStats, stats, ["match_id", "team_id"])
    return done, missing




def _roster_rows(rosters: dict, match_id: int, home_id: int, away_id: int) -> tuple[list[dict], list[dict]]:
    players, appearances = {}, []
    for side, team_id in (("h", home_id), ("a", away_id)):
        for p in (rosters.get(side) or {}).values():
            pid = int(p["player_id"])
            players[pid] = {"id": pid, "name": html.unescape(p["player"])}
            appearances.append(
                {
                    "match_id": match_id,
                    "player_id": pid,
                    "team_id": team_id,
                    "position": p["position"],
                    "started": p["position"] != "Sub",
                    "minutes": int(p["time"]),
                    "goals": int(p["goals"]),
                    "assists": int(p["assists"]),
                    "shots": int(p["shots"]),
                    "key_passes": int(p["key_passes"]),
                    "xg": round(float(p["xG"]), 4),
                    "xa": round(float(p["xA"]), 4),
                    "xg_chain": round(float(p["xGChain"]), 4),
                    "xg_buildup": round(float(p["xGBuildup"]), 4),
                    "yellow_cards": int(p["yellow_card"]),
                    "red_cards": int(p["red_card"]),
                }
            )
    return list(players.values()), appearances
