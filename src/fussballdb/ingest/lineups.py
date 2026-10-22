"""Voraussichtliche Aufstellungen von ligainsider.de (Teamseiten).

Jede Teamseite zeigt im Block "Voraussichtliche Aufstellung und Ergebnisse" vor dem Spiel die
erwartete Elf und nach dem Spiel die tatsächliche. Pro Position steht zuerst der Starter, darunter
(sub_child) Alternativen bzw. Einwechslungen; team_squad_area ist die übrige Bank. Jeder Abruf wird
als Schnappschuss gespeichert, damit sich später testen lässt, was vor dem Anpfiff bekannt war."""

import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from fussballdb.db.models import LineupSnapshot, Match, Team
from fussballdb.ingest.absences import BROWSER_HEADERS, PlayerMatcher
from fussballdb.ingest.http import get_text

BASE = "https://www.ligainsider.de"
BERLIN = ZoneInfo("Europe/Berlin")
PLAYER_HREF = re.compile(r"^/([a-z0-9-]+)_(\d+)/$")
TEAM_HREF = re.compile(r"^/([a-z0-9-]+)/(\d+)/kader/$")
KICKOFF = re.compile(r"(\d{2}\.\d{2}\.\d{4}) \| (\d{2}:\d{2})")
KICKOFF_RELATIVE = re.compile(r"(Heute|Gestern|Morgen)\s*\|?\s*(\d{2}:\d{2})")
RELATIVE_DAYS = {"Gestern": -1, "Heute": 0, "Morgen": 1}


def slugify(name: str) -> str:
    name = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def team_pages(attempts: int = 3) -> list[tuple[str, str]]:
    """(slug, URL) aller aktuellen Bundesliga-Teams laut Ligainsider. Die Seite kommt gelegentlich ohne
    Vereinslinks (andere Variante beim Laden); dann nach kurzer Pause erneut abrufen."""
    import time

    pages: dict[str, str] = {}
    for attempt in range(attempts):
        soup = BeautifulSoup(get_text(f"{BASE}/bundesliga/tabelle/", headers=BROWSER_HEADERS), "html.parser")
        for a in soup.select("a[href]"):
            m = TEAM_HREF.match(a["href"])
            if m:
                pages[m.group(1)] = f"{BASE}/{m.group(1)}/{m.group(2)}/"
        if pages:
            break
        time.sleep(5 * (attempt + 1))
    return sorted(pages.items())


def resolve_team(slug: str, teams: list[Team]) -> Team | None:
    by_slug = {slugify(t.name): t for t in teams}
    if slug in by_slug:
        return by_slug[slug]
    hits = [t for s, t in by_slug.items() if s.startswith(slug) or slug.startswith(s)]
    return hits[0] if len(hits) == 1 else None


def parse_kickoff(text: str, now: datetime) -> datetime | None:
    m = KICKOFF.search(text)
    if m:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d.%m.%Y %H:%M").replace(tzinfo=BERLIN)
    m = KICKOFF_RELATIVE.search(text)
    if m:
        day = (now.astimezone(BERLIN) + timedelta(days=RELATIVE_DAYS[m.group(1)])).date()
        hour, minute = map(int, m.group(2).split(":"))
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BERLIN)
    return None


def parse_lineup(html: str, now: datetime | None = None) -> dict | None:
    """Liefert {"kickoff": datetime | None, "players": [(rolle, reihe, slug, ligainsider_id)]}."""
    soup = BeautifulSoup(html, "html.parser")
    area = soup.select_one("div.stadium_container_area")
    if area is None:
        return None
    kickoff = parse_kickoff(area.get_text(" ", strip=True), now or datetime.now(tz=BERLIN))
    players, seen = [], set()

    def add(role, row, a):
        pm = PLAYER_HREF.match(a.get("href", ""))
        if pm and pm.group(2) not in seen:
            seen.add(pm.group(2))
            players.append((role, row, pm.group(1), int(pm.group(2))))

    for row_el in area.select("div.player_position_row"):
        row_cls = next((c for c in row_el.get("class", []) if re.fullmatch(r"player_position_row\d", c)), "player_position_row1")
        row = int(row_cls[-1])
        for col in row_el.select("div.player_position_column"):
            # Mehrere Spieler auf einer Position: der erste sub_child ist der Starter,
            # die weiteren sind Einwechslungen (gespielt) bzw. Alternativen (Vorschau)
            children = col.find_all("div", class_="sub_child", recursive=False)
            blocks = children if children else [col]
            for i, block in enumerate(blocks):
                link = block.select_one("a[href]")
                if link is not None:
                    add("start" if i == 0 else "alternative", row, link)
    container = area.find_parent("div", class_="content") or soup
    for a in container.select("div.team_squad_area a[href]"):
        add("bank", None, a)
    return {"kickoff": kickoff, "players": players}


def ingest(session: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=BERLIN)
    teams = list(session.scalars(select(Team)))
    matcher = PlayerMatcher(session)
    stats = {"teams": 0, "vorschau": 0, "gespielt": 0, "ohne_team": [], "ohne_spieler_zuordnung": 0, "fehler": []}
    for slug, url in team_pages():
        team = resolve_team(slug, teams)
        if team is None:
            stats["ohne_team"].append(slug)
            continue
        try:
            parsed = parse_lineup(get_text(url, headers=BROWSER_HEADERS, delay=1.5), now)
        except Exception as exc:  # eine kaputte Seite soll den Lauf nicht abbrechen
            stats["fehler"].append(f"{slug}: {exc}")
            continue
        if not parsed or not parsed["players"]:
            stats["fehler"].append(f"{slug}: keine Aufstellung gefunden")
            continue
        kickoff = parsed["kickoff"]
        status = "vorschau" if kickoff is None or kickoff > now else "gespielt"
        match_id = None
        if kickoff is not None:
            match_id = session.scalar(
                select(Match.id).where(
                    (Match.home_team_id == team.id) | (Match.away_team_id == team.id),
                    Match.kickoff.between(kickoff.replace(hour=0, minute=0), kickoff.replace(hour=23, minute=59)),
                )
            )
        for role, row, pslug, lid in parsed["players"]:
            name = pslug.replace("-", " ").title()
            pid = matcher.match(team.id, name)
            stats["ohne_spieler_zuordnung"] += pid is None
            session.add(LineupSnapshot(fetched_at=now, team_id=team.id, match_id=match_id, match_kickoff=kickoff,
                                       status=status, role=role, position_row=row, player_name=name,
                                       ligainsider_id=lid, player_id=pid))
        stats["teams"] += 1
        stats[status] += 1
    return stats
