"""Zugriff auf die (inoffizielle) Kickbase-API mit dem eigenen Konto.

Das Passwort wird nie gespeichert: `fussballdb kickbase-login` fragt es im Terminal ab, meldet sich an und
legt nur das Token in .cache/kickbase.json ab (nicht im Git, Dateirechte 600). Alle Importe lesen damit."""

import json
import os
from pathlib import Path

import httpx

from fussballdb.config import CACHE_DIR

API = "https://api.kickbase.com"
TOKEN_FILE: Path = CACHE_DIR / "kickbase.json"


class KickbaseAuthError(RuntimeError):
    pass


def login(email: str, password: str) -> dict:
    resp = httpx.post(f"{API}/v4/user/login", json={"em": email, "pass": password, "loy": False, "rep": {}},
                      headers={"Accept": "application/json"}, timeout=30)
    if resp.status_code != 200:
        raise KickbaseAuthError(f"Anmeldung fehlgeschlagen ({resp.status_code}). E-Mail und Passwort prüfen.")
    data = resp.json()
    token = data.get("tkn") or data.get("token")
    if not token:
        raise KickbaseAuthError("Anmeldung ohne Token beantwortet, die API hat sich vermutlich geändert.")
    leagues = [{"id": l.get("id"), "name": l.get("n") or l.get("name")} for l in data.get("srvl", []) or []]
    session = {"token": token, "expires": data.get("tknex"), "leagues": leagues}
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(session, ensure_ascii=False, indent=2))
    os.chmod(TOKEN_FILE, 0o600)
    return {"expires": session["expires"], "leagues": leagues, "keys": sorted(data.keys())}


def session() -> dict:
    if not TOKEN_FILE.exists():
        raise KickbaseAuthError("Kein Kickbase-Zugang hinterlegt. Einmal `uv run fussballdb kickbase-login` ausführen.")
    return json.loads(TOKEN_FILE.read_text())


RETRY_WAIT = (3, 10, 30, 60)  # Sekunden; Kickbase trennt bei Last gelegentlich die Verbindung


def get(path: str, **params):
    """GET auf die Kickbase-API mit dem gespeicherten Token; wiederholt bei Verbindungs- und Serverfehlern."""
    import time

    headers = {"Authorization": f"Bearer {session()['token']}", "Accept": "application/json"}
    for attempt in range(len(RETRY_WAIT) + 1):
        try:
            resp = httpx.get(f"{API}{path}", params=params or None, timeout=60, headers=headers)
        except httpx.TransportError:
            if attempt == len(RETRY_WAIT):
                raise
            time.sleep(RETRY_WAIT[attempt])
            continue
        if resp.status_code in (401, 403):
            raise KickbaseAuthError("Kickbase-Token abgelaufen oder ungültig. `uv run fussballdb kickbase-login` erneut ausführen.")
        if (resp.status_code == 429 or resp.status_code >= 500) and attempt < len(RETRY_WAIT):
            time.sleep(RETRY_WAIT[attempt])
            continue
        resp.raise_for_status()
        return resp.json()
    raise AssertionError("unreachable")


# --- Import -----------------------------------------------------------------------------------------

import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

DELAY = 0.35  # Pause zwischen Anfragen (inoffizielle API, sparsam bleiben)
BERLIN = ZoneInfo("Europe/Berlin")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def _team_map(session: Session) -> dict[int, int]:
    """Kickbase-Team-ID -> unsere Team-ID über die Kurznamen der Tabelle ("Bayern", "Gladbach" …)."""
    from fussballdb.ingest.team_mapping import TeamResolver

    resolver = TeamResolver(session)
    out = {}
    for t in get("/v4/competitions/1/table")["it"]:
        team_id = resolver.find(t["tn"])
        if team_id:
            out[int(t["tid"])] = team_id
    return out


def _match_lookup(session: Session) -> dict:
    """(Berliner Datum, Heimtore, Gasttore) -> Liste von match_id, um Kickbase-Spiele zuzuordnen."""
    rows = session.execute(text(
        "SELECT id, (kickoff AT TIME ZONE 'Europe/Berlin')::date, home_goals, away_goals FROM match WHERE finished")).all()
    out: dict = {}
    for mid, d, hg, ag in rows:
        out.setdefault((d, hg, ag), []).append(mid)
    return out


def ingest_players(session: Session, history: bool = True, mv_days: int = 365, progress=None) -> dict:
    """Alle Spieler der 18 Bundesligisten mit Marktwert, Punkte-Historie und Marktwert-Verlauf."""
    from fussballdb.db.models import KbMarketValue, KbPlayer, KbPoints
    from fussballdb.ingest.absences import PlayerMatcher
    from fussballdb.ingest.upsert import upsert

    teams = _team_map(session)
    matcher = PlayerMatcher(session, all_time=True)
    # in den letzten 24 Stunden vollständig geladene Spieler überspringen (Fortsetzen nach Abbruch)
    done_today = set(session.execute(text(
        "SELECT p.kb_id FROM kb_player p WHERE p.updated_at > now() - interval '24 hours' "
        "AND EXISTS (SELECT 1 FROM kb_market_value v WHERE v.kb_id = p.kb_id AND v.day >= current_date - 2)")).scalars())
    matches = _match_lookup(session)
    stats = {"spieler": 0, "zugeordnet": 0, "punkte": 0, "marktwerte": 0}
    for kb_tid, team_id in teams.items():
        roster = get(f"/v4/competitions/1/teams/{kb_tid}/teamprofile")["it"]
        time.sleep(DELAY)
        for p in roster:
            kb_id = int(p["i"])
            if history and kb_id in done_today:
                stats["spieler"] += 1
                continue
            detail = get(f"/v4/competitions/1/players/{kb_id}")
            time.sleep(DELAY)
            first, last = detail.get("fn") or "", detail.get("ln") or p.get("n")
            pid = matcher.match(team_id, f"{first} {last}".strip()) or matcher.match(team_id, last)
            upsert(session, KbPlayer, [{
                "kb_id": kb_id, "first_name": first or None, "last_name": last, "kb_team_id": kb_tid,
                "team_id": team_id, "player_id": pid, "position": p["pos"], "status": p.get("st"),
                "market_value": p.get("mv"), "mv_trend": p.get("mvt"), "total_points": detail.get("tp"),
                "avg_points": p.get("ap"), "image": p.get("pim"), "updated_at": datetime.now(timezone.utc),
            }], ["kb_id"])
            stats["spieler"] += 1
            stats["zugeordnet"] += pid is not None
            if history:
                rows = []
                for season in get(f"/v4/competitions/1/players/{kb_id}/performance").get("it", []):
                    for m in season.get("ph", []):
                        if "md" not in m or m.get("p") is None:
                            continue
                        kickoff = datetime.fromisoformat(m["md"].replace("Z", "+00:00"))
                        day = kickoff.astimezone(BERLIN).date()
                        cands = matches.get((day, m.get("t1g"), m.get("t2g"))) or []
                        minutes = int(re.sub(r"\D", "", str(m.get("mp", "0"))) or 0)
                        rows.append({"kb_id": kb_id, "kickoff": kickoff, "match_id": cands[0] if len(cands) == 1 else None,
                                     "season": season.get("ti", ""), "matchday": m.get("day", 0),
                                     "points": int(m["p"]), "minutes": minutes})
                time.sleep(DELAY)
                upsert(session, KbPoints, rows, ["kb_id", "kickoff"])
                stats["punkte"] += len(rows)
                mv = get(f"/v4/competitions/1/players/{kb_id}/marketvalue/{mv_days}").get("it", [])
                time.sleep(DELAY)
                # dt = Tage seit 1.1.1970
                upsert(session, KbMarketValue, [{"kb_id": kb_id, "day": date(1970, 1, 1) + timedelta(days=int(x["dt"])),
                                                 "value": x["mv"]} for x in mv], ["kb_id", "day"])
                stats["marktwerte"] += len(mv)
            session.commit()
        if progress:
            progress(kb_tid, len(roster))
    return stats


def ingest_league(session: Session) -> dict:
    """Transfermarkt und eigener Kader in der (ersten) eigenen Liga."""
    from fussballdb.db.models import KbLeagueEntry

    league_id = int(session_info_league())
    session.execute(delete(KbLeagueEntry).where(KbLeagueEntry.league_id == league_id))
    market = get(f"/v4/leagues/{league_id}/market").get("it", [])
    squad = get(f"/v4/leagues/{league_id}/squad").get("it", [])
    for p in market:
        session.add(KbLeagueEntry(league_id=league_id, kb_id=int(p["i"]), kind="markt", price=p.get("prc"),
                                  expires_in=p.get("exs")))
    for p in squad:
        session.add(KbLeagueEntry(league_id=league_id, kb_id=int(p["i"]), kind="kader", price=p.get("mv")))
    return {"markt": len(market), "kader": len(squad)}


def session_info_league() -> str:
    leagues = session().get("leagues") or []
    if not leagues:
        raise KickbaseAuthError("Keine Kickbase-Liga gefunden.")
    return leagues[0]["id"]


def ingest_daily(session: Session) -> dict:
    """Schneller Tageslauf: Marktwert und Status aller Spieler (18 Teamprofile) plus Markt und Kader
    der eigenen Liga. Der Marktwert des Tages wird in kb_market_value fortgeschrieben."""
    from fussballdb.db.models import KbMarketValue, KbPlayer
    from fussballdb.ingest.upsert import upsert

    teams = _team_map(session)
    known = set(session.execute(select(KbPlayer.kb_id)).scalars())
    today = date.today()
    updated, new = 0, 0
    for kb_tid, team_id in teams.items():
        for p in get(f"/v4/competitions/1/teams/{kb_tid}/teamprofile")["it"]:
            kb_id = int(p["i"])
            if kb_id not in known:
                new += 1  # neue Spieler kommen mit dem nächsten vollständigen Lauf (Name, Zuordnung, Historie)
                continue
            upsert(session, KbPlayer, [{"kb_id": kb_id, "kb_team_id": kb_tid, "team_id": team_id, "status": p.get("st"),
                                        "market_value": p.get("mv"), "mv_trend": p.get("mvt"), "avg_points": p.get("ap"),
                                        "last_name": p.get("n"), "position": p["pos"]}], ["kb_id"])
            if p.get("mv"):
                upsert(session, KbMarketValue, [{"kb_id": kb_id, "day": today, "value": p["mv"]}], ["kb_id", "day"])
            updated += 1
        time.sleep(DELAY)
    league = ingest_league(session)
    return {"aktualisiert": updated, "neu": new, **league}
