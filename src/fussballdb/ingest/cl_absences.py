"""Verletzte und Gesperrte der Champions-League-Teams von Transfermarkt (je Verein die Seite "Sperren und
Verletzungen", dazu die Kaderseite für die Marktwerte). Wie wichtig ein Spieler ist, wird über seinen Anteil
am Kaderwert geschätzt; für die Prognose wird das noch nicht genutzt (keine Historie zum Testen), nur angezeigt.
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.models import EuAbsence
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.http import get_text
from fussballdb.ingest.squad_values import parse_value

ABSENCES = "https://www.transfermarkt.de/x/sperrenundverletzungen/verein/{tm}"
SQUAD = "https://www.transfermarkt.de/x/kader/verein/{tm}/saison_id/{season}"


def _player_id(row) -> tuple[int | None, str | None]:
    link = row.select_one("td.hauptlink a[href*='/spieler/']") or row.select_one("a[href*='/spieler/']")
    if not link:
        return None, None
    m = re.search(r"/spieler/(\d+)", link["href"])
    return (int(m.group(1)) if m else None), (link.get("title") or link.get_text(strip=True))


def squad_values(tm_id: int, season: int) -> dict[int, float]:
    soup = BeautifulSoup(get_text(SQUAD.format(tm=tm_id, season=season), headers=BROWSER_HEADERS, delay=2.0), "html.parser")
    out = {}
    for tr in soup.select("table.items > tbody > tr"):
        pid, _ = _player_id(tr)
        cells = tr.find_all("td", recursive=False)
        value = parse_value(cells[-1].get_text(strip=True)) if cells else None
        if pid and value:
            out[pid] = value
    return out


def absences(tm_id: int) -> list[dict]:
    """Spieler aus den Abschnitten Verletzungen und Sperren (nicht "Sperre droht")."""
    soup = BeautifulSoup(get_text(ABSENCES.format(tm=tm_id), headers=BROWSER_HEADERS, delay=2.0), "html.parser")
    tables = soup.select("table.items")
    out = []
    if not tables:
        return out
    kind = None
    for tr in tables[0].select("tbody > tr"):
        cells = tr.find_all("td", recursive=False)
        label = tr.get_text(" ", strip=True)
        if len(cells) == 1:  # Zwischenüberschrift
            kind = "verletzt" if label.startswith("Verletz") else "gesperrt" if label.startswith("Sperre") else None
            continue
        pid, name = _player_id(tr)
        if not name or kind is None:
            continue
        texts = [c.get_text(" ", strip=True) for c in cells]
        # Spalten: Spieler, Alter, Grund, seit, bis voraussichtlich, verpasste Spiele
        reason = texts[2] if len(texts) > 2 else None
        until = texts[4] if len(texts) > 4 else None
        out.append({"tm_player_id": pid, "player_name": name, "kind": kind, "reason": reason or None,
                    "until": until or None})
    return out


def ingest(session: Session, log=print) -> dict:
    """Ausfälle aller Teams mit offenen CL-Spielen laden; frühere Einträge dieser Teams werden inaktiv."""
    teams = session.execute(text("""
        SELECT DISTINCT t.id, t.tm_id, t.name, m.season FROM eu_match m
        JOIN eu_team t ON t.id IN (m.home_id, m.away_id)
        WHERE m.competition = 'CL' AND NOT m.finished AND m.kickoff BETWEEN now() AND now() + interval '14 days'
          AND t.tm_id IS NOT NULL""")).all()
    now = datetime.now().astimezone()
    total = 0
    for team_id, tm_id, name, season in teams:
        try:
            rows = absences(tm_id)
            values = squad_values(tm_id, season) if rows else {}
        except Exception as exc:
            log(f"  {name}: {exc}")
            continue
        squad_total = sum(values.values()) or None
        session.execute(text("UPDATE eu_absence SET active = false WHERE team_id = :t AND active"), {"t": team_id})
        for r in rows:
            v = values.get(r["tm_player_id"])
            session.add(EuAbsence(team_id=team_id, value_eur=v, value_share=(v / squad_total) if v and squad_total else None,
                                  fetched_at=now, active=True, **r))
        total += len(rows)
    return {"teams": len(teams), "ausfaelle": total}
