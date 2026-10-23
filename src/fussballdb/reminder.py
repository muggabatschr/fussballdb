"""Erinnerung vor dem Tippschluss: eine Mac-Mitteilung mit allen Tipps des nächsten Bundesliga-Spieltags,
sobald dessen erstes Spiel in weniger als `hours` Stunden beginnt. Je Spieltag nur einmal (Merkliste in
.cache/erinnerung.json). Dazu Hinweise auf Verletzte im eigenen Kickbase-Kader, falls vorhanden."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from fussballdb.config import CACHE_DIR
from fussballdb.db.session import engine
from fussballdb.ingest.team_mapping import COLLOQUIAL
from fussballdb.model.ensemble import MODEL_VERSION

STATE = CACHE_DIR / "erinnerung.json"
BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _short(name: str) -> str:
    return (COLLOQUIAL.get(name) or [name])[0]


def next_matchday() -> tuple[int, int, datetime, list[tuple]] | None:
    """(Saison, Spieltag, erster Anpfiff, [(Heim, Gast, Tipp Heim, Tipp Gast, Anstoß)]) des nächsten Spieltags."""
    with engine.connect() as conn:
        first = conn.execute(text("""
            SELECT s.start_year, m.matchday FROM match m JOIN season s ON s.id = m.season_id
            WHERE NOT m.finished AND m.kickoff > now() ORDER BY m.kickoff LIMIT 1""")).first()
        if not first:
            return None
        rows = conn.execute(text("""
            SELECT ht.name, at.name, p.tip_home, p.tip_away, m.kickoff
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            LEFT JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
            WHERE s.start_year = :y AND m.matchday = :md ORDER BY m.kicktipp_pos NULLS LAST, m.kickoff, m.id"""),
            {"y": first[0], "md": first[1], "v": MODEL_VERSION}).all()
    return first[0], first[1], min(r[4] for r in rows), rows


def injured_own_players() -> list[str]:
    """Spieler im eigenen Kickbase-Kader, die laut Kickbase oder Transfermarkt ausfallen."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT trim(coalesce(k.first_name, '') || ' ' || k.last_name)
            FROM kb_league_entry e JOIN kb_player k ON k.kb_id = e.kb_id
            LEFT JOIN player_absence a ON a.player_id = k.player_id AND a.active
            WHERE e.kind = 'kader' AND (coalesce(k.status, 0) IN (1, 4) OR a.id IS NOT NULL)""")).all()
    return [r[0] for r in rows]


def notify(title: str, message: str) -> None:
    def q(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e", f'display notification "{q(message)}" with title "{q(title)}" sound name "default"'],
                   check=False)


def remind(hours: float = 3.0, force: bool = False) -> str:
    nxt = next_matchday()
    if nxt is None:
        return "Kein offener Spieltag."
    season, md, first, rows = nxt
    now = datetime.now(timezone.utc)
    key = f"BL-{season}-{md}"
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    due = first - timedelta(hours=hours) <= now < first
    if not force and (not due or key in state):
        return f"{md}. Spieltag beginnt {first.astimezone(BERLIN):%d.%m. %H:%M}, noch keine Erinnerung nötig."
    local = first.astimezone(BERLIN)
    tips = " · ".join(f"{_short(h)}–{_short(a)} {th}:{ta}" for h, a, th, ta, _ in rows if th is not None)
    notify(f"Tipps {md}. Spieltag, Anpfiff {WEEKDAYS[local.weekday()]} {local:%H:%M}", tips or "Noch keine Tipps berechnet")
    injured = injured_own_players()
    if injured:
        notify("Kickbase: Ausfall im Kader", ", ".join(injured))
    if not force:
        state[key] = now.isoformat()
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))
    return f"Erinnerung verschickt: {tips}" + (f" | Kickbase-Ausfälle: {', '.join(injured)}" if injured else "")
