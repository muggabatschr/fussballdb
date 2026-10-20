"""Kaderwerte von Transfermarkt zu Stichtagen. Die Seite listet die heutigen Vereine einer Liga mit
ihrem Wert zum Stichtag; deshalb werden 1. und 2. Liga abgefragt (Absteiger stehen heute in Liga 2)."""

import re
from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from fussballdb.db.models import SquadValue
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.http import get_text
from fussballdb.ingest.team_mapping import TeamResolver
from fussballdb.ingest.upsert import upsert

URL = "https://www.transfermarkt.de/x/marktwerteverein/wettbewerb/{liga}/stichtag/{stichtag}"
LEAGUES = ("L1", "L2", "L3")  # Absteiger von früher spielen heute teils in Liga 2 oder 3
UNITS = {"Mrd.": 1e9, "Mio.": 1e6, "Tsd.": 1e3}


def parse_value(text: str) -> float | None:
    m = re.match(r"([\d.,]+)\s*(Mrd\.|Mio\.|Tsd\.)", text.strip())
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", ".")) * UNITS[m.group(2)]


def stichtage(start: date, end: date) -> list[date]:
    """Jeweils der 1. eines Monats zwischen start und end."""
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def available_stichtage() -> list[date]:
    """Stichtage, die Transfermarkt anbietet (meist 1. und 15. des Monats, früher unregelmäßig)."""
    html = get_text(URL.format(liga="L1", stichtag=date.today().replace(day=1).isoformat()), headers=BROWSER_HEADERS)
    opts = BeautifulSoup(html, "html.parser").select("select[name=stichtag] option")
    return sorted({date.fromisoformat(o["value"]) for o in opts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", o.get("value", ""))})


def monthly_stichtage(start: date, end: date, available: list[date]) -> list[date]:
    """Pro Monat der erste angebotene Stichtag (2014 z. B. nur 10.07. und 23.10.)."""
    out = []
    for month in stichtage(start, end):
        in_month = [d for d in available if d.year == month.year and d.month == month.month]
        if in_month:
            out.append(min(in_month))
    return out


def ingest(session: Session, start: date, end: date | None = None) -> tuple[int, list[str]]:
    end = end or date.today()
    teams = TeamResolver(session)
    known = {alias for (source, alias) in teams._by_source if source == "transfermarkt"}
    rows, unknown = [], set()
    for d in monthly_stichtage(start, end, available_stichtage()):
        historic = d < date.today().replace(day=1)
        for liga in LEAGUES:
            html = get_text(URL.format(liga=liga, stichtag=d.isoformat()), headers=BROWSER_HEADERS,
                            cache=historic, delay=2.0)
            table = BeautifulSoup(html, "html.parser").select("table.items")
            if not table:
                continue
            for tr in table[0].select("tbody > tr"):
                link = tr.select_one("td.hauptlink a")
                cells = tr.find_all("td", recursive=False)
                if not link or len(cells) < 5:
                    continue
                club = link["title"]
                if club not in known:
                    unknown.add(club)  # Vereine, die nie in unserer Bundesliga-Datenbank waren
                    continue
                value = parse_value(cells[4].get_text(strip=True))
                if value:
                    rows.append({"team_id": teams.resolve("transfermarkt", club), "stichtag": d, "value_eur": value})
    upsert(session, SquadValue, rows, ["team_id", "stichtag"])
    return len(rows), sorted(unknown)
