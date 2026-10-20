"""Verletzungshistorie aller Bundesliga-Spieler seit 2023/24 von Transfermarkt.

Ablauf: Vereins-IDs aus den Kaderwert-Seiten -> Kader je Saison -> Verletzungsseite je Spieler
(neueste zuerst, mehrere Seiten). Alle Seiten werden gecacht, ein zweiter Lauf ist schnell."""

import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fussballdb.db.models import PlayerInjury, Season
from fussballdb.db.session import engine
from fussballdb.ingest.absences import BROWSER_HEADERS, PlayerMatcher
from fussballdb.ingest.http import get_text
from fussballdb.ingest.squad_values import URL as VALUES_URL
from fussballdb.ingest.team_mapping import TeamResolver
from fussballdb.ingest.upsert import upsert

TM = "https://www.transfermarkt.de"
DELAY = 2.0


def _html(url: str) -> BeautifulSoup:
    return BeautifulSoup(get_text(url, headers=BROWSER_HEADERS, cache=True, delay=DELAY), "html.parser")


def club_ids(teams: TeamResolver) -> dict[int, tuple[str, int]]:
    """team_id -> (Transfermarkt-Slug, Vereins-ID)."""
    out = {}
    for liga in ("L1", "L2", "L3"):
        soup = _html(VALUES_URL.format(liga=liga, stichtag="2024-08-01"))
        for a in soup.select("td.hauptlink a[href]"):
            m = re.match(r"^/([^/]+)/startseite/verein/(\d+)", a["href"])
            if m and ("transfermarkt", a["title"]) in teams._by_source:
                out[teams.resolve("transfermarkt", a["title"])] = (m.group(1), int(m.group(2)))
    return out


def _date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _int(value: str) -> int | None:
    m = re.search(r"\d+", value.replace(".", ""))
    return int(m.group()) if m else None


def player_injuries(slug: str, tm_id: int, first_season: int) -> list[dict]:
    rows, page = [], 1
    while True:
        url = f"{TM}/{slug}/verletzungen/spieler/{tm_id}" + (f"/page/{page}" if page > 1 else "")
        soup = _html(url)
        trs = soup.select("table.items tbody tr")
        stop = False
        for tr in trs:
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
            if len(tds) < 6:
                continue
            season_start = 2000 + int(tds[0][:2]) if re.match(r"\d{2}/\d{2}", tds[0]) else None
            if season_start is not None and season_start < first_season:
                stop = True
                break
            club = tr.select_one("td a[title]")
            rows.append({"injury": tds[1][:120], "von": _date(tds[2]), "bis": _date(tds[3]),
                         "days": _int(tds[4]), "missed_games": _int(tds[5]),
                         "club": club["title"] if club else None})
        has_next = soup.select_one(f'a[href$="/page/{page + 1}"]') is not None
        if stop or not has_next or not trs:
            return [r for r in rows if r["von"] is not None]
        page += 1


def ingest(session: Session, first_season: int = 2023, progress=None) -> tuple[int, list[str]]:
    """Liefert (Anzahl Verletzungen, Liste übersprungener Seiten). Ein zweiter Lauf holt die
    übersprungenen nach, alles andere kommt aus dem Cache."""
    teams = TeamResolver(session)
    clubs = club_ids(teams)
    matcher = PlayerMatcher(session, all_time=True)
    seasons = [s.start_year for s in session.scalars(select(Season)) if s.start_year >= first_season]
    players: dict[int, dict] = {}
    failed: list[str] = []
    with engine.connect() as conn:
        for year in seasons:
            team_ids = [r[0] for r in conn.execute(text(
                "SELECT DISTINCT unnest(ARRAY[home_team_id, away_team_id]) FROM match m JOIN season s ON s.id = m.season_id "
                "WHERE s.start_year = :y"), {"y": year})]
            for team_id in team_ids:
                slug, cid = clubs[team_id]
                try:
                    soup = _html(f"{TM}/{slug}/kader/verein/{cid}/saison_id/{year}")
                except Exception as exc:  # ein fehlender Kader soll den Lauf nicht abbrechen
                    failed.append(f"Kader {slug} {year}: {exc}")
                    continue
                for a in soup.select("table.items td.hauptlink a[href*='/profil/spieler/']"):
                    parts = a["href"].split("/")
                    tm_id = int(parts[-1])
                    p = players.setdefault(tm_id, {"slug": parts[1], "name": a.get_text(strip=True), "teams": set()})
                    p["teams"].add(team_id)
    total = 0
    for i, (tm_id, p) in enumerate(sorted(players.items()), 1):
        try:
            injuries = player_injuries(p["slug"], tm_id, first_season)
        except Exception as exc:
            failed.append(f"{p['name']}: {exc}")
            continue
        pid = next((x for x in (matcher.match(t, p["name"]) for t in p["teams"]) if x), None)
        rows = []
        for inj in injuries:
            club = inj.pop("club")
            team_id = teams.resolve("transfermarkt", club) if club and ("transfermarkt", club) in teams._by_source else None
            rows.append({"tm_player_id": tm_id, "player_name": p["name"], "player_id": pid, "team_id": team_id, **inj})
        # gleiche Verletzung kann doppelt gelistet sein (Seitenwechsel); Schlüssel eindeutig machen
        rows = list({(r["von"], r["injury"]): r for r in rows}.values())
        upsert(session, PlayerInjury, rows, ["tm_player_id", "von", "injury"])
        session.commit()
        total += len(rows)
        if progress:
            progress(i, len(players), p["name"], len(rows))
    return total, failed
