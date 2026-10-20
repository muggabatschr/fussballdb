"""Aktuelle Ausfälle: Verletzte/Kranke von Transfermarkt, Sperren aus den Karten der Kaderdaten."""

import re
import unicodedata

from bs4 import BeautifulSoup
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from fussballdb.db.models import PlayerAbsence
from fussballdb.ingest.http import get_text
from fussballdb.ingest.team_mapping import TeamResolver

TM_URL = "https://www.transfermarkt.de/bundesliga/verletztespieler/wettbewerb/L1"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

# Spieler, die in den letzten ~12 Monaten für ein Team gespielt haben
RECENT_PLAYERS_SQL = text(
    """
    SELECT DISTINCT pm.team_id, p.id, p.name
    FROM player_match pm JOIN player p ON p.id = pm.player_id JOIN match m ON m.id = pm.match_id
    WHERE m.kickoff > now() - interval '400 days'
    """
)

# Letztes Spiel je Team + Karten der Spieler darin + Gelbe der laufenden Saison
SUSPENSION_SQL = text(
    """
    WITH upcoming AS (
        SELECT DISTINCT t.team_id, m.season_id
        FROM match m
        CROSS JOIN LATERAL (VALUES (m.home_team_id), (m.away_team_id)) AS t(team_id)
        WHERE NOT m.finished
    ),
    last_match AS (
        SELECT DISTINCT ON (t.team_id) t.team_id, m.id AS match_id, m.season_id
        FROM match m
        CROSS JOIN LATERAL (VALUES (m.home_team_id), (m.away_team_id)) AS t(team_id)
        JOIN upcoming u ON u.team_id = t.team_id AND u.season_id = m.season_id
        WHERE m.finished
        ORDER BY t.team_id, m.kickoff DESC
    )
    SELECT lm.team_id, p.id AS player_id, p.name, pm.red_cards, pm.yellow_cards,
           (SELECT sum(x.yellow_cards) FROM player_match x JOIN match mm ON mm.id = x.match_id
            WHERE x.player_id = pm.player_id AND x.team_id = lm.team_id
              AND mm.season_id = lm.season_id) AS season_yellows
    FROM last_match lm
    JOIN player_match pm ON pm.match_id = lm.match_id AND pm.team_id = lm.team_id
    JOIN player p ON p.id = pm.player_id
    WHERE pm.red_cards > 0 OR pm.yellow_cards > 0
    """
)


SPECIAL_CHARS = str.maketrans({"ı": "i", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "æ": "ae", "ß": "ss", "đ": "d"})


def normalize(name: str) -> str:
    """Kleinbuchstaben ohne Akzente; Bindestriche werden Leerzeichen. Umschreibungen wie "oe" für "ö"
    (Ligainsider) werden auf beiden Seiten gleich behandelt, damit Königsdörffer = Koenigsdoerffer."""
    name = unicodedata.normalize("NFKD", name.translate(SPECIAL_CHARS))
    name = name.encode("ascii", "ignore").decode().lower().replace("-", " ")
    name = re.sub(r"[^a-z ]", "", name)
    name = re.sub(r"([aou])e", r"\1", name)
    return re.sub(r"\s+", " ", name).strip()


def _compact(name: str) -> str:
    return name.replace(" ", "")


ALL_PLAYERS_SQL = text(
    """
    SELECT DISTINCT pm.team_id, p.id, p.name
    FROM player_match pm JOIN player p ON p.id = pm.player_id
    """
)


class PlayerMatcher:
    def __init__(self, session: Session, all_time: bool = False):
        """all_time=False: nur Spieler der letzten ~12 Monate (aktuelle Kader)."""
        self.by_team: dict[int, list[tuple[int, str]]] = {}
        for team_id, pid, name in session.execute(ALL_PLAYERS_SQL if all_time else RECENT_PLAYERS_SQL):
            self.by_team.setdefault(team_id, []).append((pid, normalize(name)))

    def match(self, team_id: int, name: str) -> int | None:
        target = normalize(name)
        candidates = self.by_team.get(team_id, [])
        for pid, n in candidates:
            if _compact(n) == _compact(target):  # "Min-Jae Kim" = "Minjae Kim"
                return pid
        parts = target.split()
        if not parts:
            return None
        # Nachname gleich, bzw. bei Einzelnamen ("Silas") Vorname gleich
        if len(parts) == 1:
            hits = [pid for pid, n in candidates if parts[0] in n.split()]
        else:
            hits = [pid for pid, n in candidates if n.split() and n.split()[-1] == parts[-1]]
        return hits[0] if len(hits) == 1 else None


def fetch_injuries() -> list[dict]:
    soup = BeautifulSoup(get_text(TM_URL, headers=BROWSER_HEADERS), "html.parser")
    rows = []
    for tr in soup.select("table.items > tbody > tr"):
        cells = tr.find_all("td", recursive=False)
        player = tr.select_one('td.hauptlink a[href*="/profil/spieler/"]')
        club = cells[1].select_one("a[title]") if len(cells) > 1 else None
        if not player or not club:
            continue
        rows.append(
            {
                "player_name": player.get_text(strip=True),
                "club": club["title"],
                "reason": cells[2].get_text(strip=True) or None,
                "expected_return": cells[3].get_text(strip=True) or None,
                "market_value": cells[4].get_text(strip=True) or None,
            }
        )
    return rows


def ingest(session: Session) -> dict:
    teams = TeamResolver(session)
    players = PlayerMatcher(session)
    session.execute(update(PlayerAbsence).where(PlayerAbsence.active).values(active=False))
    stats = {"injuries": 0, "unmatched_players": [], "suspensions": 0}

    for r in fetch_injuries():
        team_id = teams.resolve("transfermarkt", r["club"])
        pid = players.match(team_id, r["player_name"])
        if pid is None:
            stats["unmatched_players"].append(f"{r['player_name']} ({r['club']})")
        session.add(PlayerAbsence(team_id=team_id, player_id=pid, player_name=r["player_name"],
                                  kind="injury", reason=r["reason"], expected_return=r["expected_return"],
                                  market_value=r["market_value"], source="transfermarkt"))
        stats["injuries"] += 1

    for team_id, pid, name, red, yellow, season_yellows in session.execute(SUSPENSION_SQL):
        reason = None
        if red:
            reason = "Rote/Gelb-Rote Karte im letzten Spiel"
        elif yellow and season_yellows and season_yellows % 5 == 0:
            reason = f"{season_yellows}. Gelbe Karte"
        if reason:
            session.add(PlayerAbsence(team_id=team_id, player_id=pid, player_name=name, kind="suspension",
                                      reason=reason, expected_return="nächstes Spiel", source="karten"))
            stats["suspensions"] += 1
    return stats
