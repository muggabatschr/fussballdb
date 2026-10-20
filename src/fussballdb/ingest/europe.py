"""Daten für die Champions-League-Prognose.

- Europapokal-Spiele (Champions League, Europa League) von OpenLigaDB
- Ligaspiele der wichtigsten europäischen Ligen von football-data.co.uk: Sie machen Teams aus
  verschiedenen Ländern über eine gemeinsame Elo vergleichbar (model/europe.py)
- Kaderwerte aller Vereine dieser Ligen von Transfermarkt (Startwert der Elo und eigenes Signal)

Teams aus Ländern ohne football-data-Liga (z. B. Tschechien, Kroatien, Aserbaidschan) haben nur ihre
Europapokal-Spiele und ihren Kaderwert.
"""

import csv
import difflib
import io
import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from fussballdb.db.models import EuMatch, EuSquadValue, EuTeam, EuTeamAlias
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.http import get_json, get_text
from fussballdb.ingest.squad_values import available_stichtage, parse_value
from fussballdb.ingest.upsert import upsert

FIRST_SEASON = 2022  # Ligaspiele ab 2022/23, damit die Elo vor 2024/25 eingeschwungen ist
UK = ZoneInfo("Europe/London")  # football-data gibt Anstoßzeiten in britischer Zeit an

# football-data: Hauptligen (eine Datei je Saison) und weitere Ligen (eine Datei für alle Saisons)
FD_MAIN = ("E0", "SP1", "I1", "D1", "F1", "N1", "P1", "B1", "T1", "SC0", "G1")
FD_EXTRA = ("AUT", "SWZ", "DNK", "NOR", "SWE", "POL", "ROU")

# Transfermarkt-Wettbewerb je Land (für die Kaderwerte). Länder ohne football-data-Liga nur für
# ihre Europapokal-Teilnehmer.
TM_LEAGUE = {
    "E0": "GB1", "SP1": "ES1", "I1": "IT1", "D1": "L1", "F1": "FR1", "N1": "NL1", "P1": "PO1",
    "B1": "BE1", "T1": "TR1", "SC0": "SC1", "G1": "GR1", "AUT": "A1", "SWZ": "C1", "DNK": "DK1",
    "NOR": "NO1", "SWE": "SE1", "POL": "PL1", "ROU": "RO1",
    "SRB": "SER1", "CZE": "TS1", "CRO": "KR1", "UKR": "UKR1", "SVK": "SLO1", "CYP": "ZYP1",
    "AZE": "AZ1", "KAZ": "KAS1", "BUL": "BU1", "HUN": "UNG1", "ISR": "ISR1", "LAT": "LET1",
}

# Europapokal bei OpenLigaDB: (Wettbewerb, Kürzel, Saison). Das Kürzel wechselt je Saison;
# für eine neue Saison hier ergänzen.
EURO_COMPETITIONS = [
    ("CL", "ucl24", 2024),
    ("CL", "ucl", 2025),
    ("CL", "ucl", 2026),
    ("EL", "uel24", 2024),
]

# Europapokal-Teilnehmer: Transfermarkt-ID -> (Land/Liga, Name bei football-data, Anzeigename)
CLUBS: dict[int, tuple[str, str | None, str]] = {
    281: ("E0", "Man City", "Manchester City"),
    11: ("E0", "Arsenal", "FC Arsenal"),
    31: ("E0", "Liverpool", "FC Liverpool"),
    405: ("E0", "Aston Villa", "Aston Villa"),
    631: ("E0", "Chelsea", "FC Chelsea"),
    148: ("E0", "Tottenham", "Tottenham Hotspur"),
    762: ("E0", "Newcastle", "Newcastle United"),
    985: ("E0", "Man United", "Manchester United"),
    418: ("SP1", "Real Madrid", "Real Madrid"),
    131: ("SP1", "Barcelona", "FC Barcelona"),
    13: ("SP1", "Ath Madrid", "Atlético Madrid"),
    12321: ("SP1", "Girona", "FC Girona"),
    1050: ("SP1", "Villarreal", "FC Villarreal"),
    621: ("SP1", "Ath Bilbao", "Athletic Bilbao"),
    150: ("SP1", "Betis", "Real Betis"),
    681: ("SP1", "Sociedad", "Real Sociedad"),
    46: ("I1", "Inter", "Inter Mailand"),
    506: ("I1", "Juventus", "Juventus Turin"),
    5: ("I1", "Milan", "AC Mailand"),
    800: ("I1", "Atalanta", "Atalanta Bergamo"),
    1025: ("I1", "Bologna", "FC Bologna"),
    6195: ("I1", "Napoli", "SSC Neapel"),
    1047: ("I1", "Como", "Como 1907"),
    12: ("I1", "Roma", "AS Rom"),
    398: ("I1", "Lazio", "Lazio Rom"),
    27: ("D1", "Bayern Munich", "FC Bayern München"),
    16: ("D1", "Dortmund", "Borussia Dortmund"),
    15: ("D1", "Leverkusen", "Bayer 04 Leverkusen"),
    23826: ("D1", "RB Leipzig", "RB Leipzig"),
    79: ("D1", "Stuttgart", "VfB Stuttgart"),
    24: ("D1", "Ein Frankfurt", "Eintracht Frankfurt"),
    533: ("D1", "Hoffenheim", "TSG Hoffenheim"),
    583: ("F1", "Paris SG", "Paris Saint-Germain"),
    162: ("F1", "Monaco", "AS Monaco"),
    1082: ("F1", "Lille", "OSC Lille"),
    3911: ("F1", "Brest", "Stade Brest"),
    244: ("F1", "Marseille", "Olympique Marseille"),
    826: ("F1", "Lens", "RC Lens"),
    1041: ("F1", "Lyon", "Olympique Lyon"),
    417: ("F1", "Nice", "OGC Nizza"),
    383: ("N1", "PSV Eindhoven", "PSV Eindhoven"),
    234: ("N1", "Feyenoord", "Feyenoord Rotterdam"),
    610: ("N1", "Ajax", "Ajax Amsterdam"),
    1090: ("N1", "AZ Alkmaar", "AZ Alkmaar"),
    317: ("N1", "Twente", "FC Twente"),
    294: ("P1", "Benfica", "Benfica Lissabon"),
    336: ("P1", "Sp Lisbon", "Sporting Lissabon"),
    720: ("P1", "Porto", "FC Porto"),
    1075: ("P1", "Sp Braga", "Sporting Braga"),
    2282: ("B1", "Club Brugge", "FC Brügge"),
    3948: ("B1", "St. Gilloise", "Union Saint-Gilloise"),
    58: ("B1", "Anderlecht", "RSC Anderlecht"),
    141: ("T1", "Galatasaray", "Galatasaray"),
    36: ("T1", "Fenerbahce", "Fenerbahce"),
    114: ("T1", "Besiktas", "Besiktas"),
    371: ("SC0", "Celtic", "Celtic Glasgow"),
    124: ("SC0", "Rangers", "Glasgow Rangers"),
    683: ("G1", "Olympiakos", "Olympiakos Piräus"),
    2441: ("G1", "AEK", "AEK Athen"),
    1091: ("G1", "PAOK", "PAOK Saloniki"),
    409: ("AUT", "Salzburg", "RB Salzburg"),
    122: ("AUT", "Sturm Graz", "Sturm Graz"),
    413: ("AUT", "LASK", "LASK"),
    452: ("SWZ", "Young Boys", "Young Boys Bern"),
    190: ("DNK", "FC Copenhagen", "FC Kopenhagen"),
    865: ("DNK", "Midtjylland", "FC Midtjylland"),
    501: ("NOR", "Bodo/Glimt", "Bodø/Glimt"),
    239: ("NOR", "Viking", "Viking Stavanger"),
    496: ("SWE", "Malmo FF", "Malmö FF"),
    1101: ("SWE", "Elfsborg", "IF Elfsborg"),
    301: ("ROU", "FCSB", "FCSB"),
    159: ("SRB", None, "Roter Stern Belgrad"),
    197: ("CZE", None, "Sparta Prag"),
    62: ("CZE", None, "Slavia Prag"),
    941: ("CZE", None, "Viktoria Pilsen"),
    419: ("CRO", None, "Dinamo Zagreb"),
    660: ("UKR", None, "Schachtar Donezk"),
    338: ("UKR", None, "Dynamo Kiew"),
    540: ("SVK", None, "Slovan Bratislava"),
    45457: ("CYP", None, "Pafos FC"),
    10625: ("AZE", None, "Qarabağ Ağdam"),
    63993: ("AZE", None, "Sabah Baku"),
    10482: ("KAZ", None, "Kairat Almaty"),
    31614: ("BUL", None, "Ludogorez Rasgrad"),
    279: ("HUN", None, "Ferencváros"),
    119: ("ISR", None, "Maccabi Tel Aviv"),
    33783: ("LAT", None, "RFS Riga"),
}

# Namen bei OpenLigaDB -> Transfermarkt-ID (die Schreibweise wechselt teils von Saison zu Saison)
OLDB_NAMES: dict[str, int] = {
    "AC Mailand": 5, "AS Monaco": 162, "Aston Villa": 405, "Atalanta Bergamo": 800, "Atletico Madrid": 13,
    "BSC Young Boys": 452, "Bayer 04 Leverkusen": 15, "Benfica Lissabon": 294, "SL Benfica": 294,
    "Borussia Dortmund": 16, "Celtic Glasgow": 371, "Dinamo Zagreb": 419, "FC Arsenal": 11,
    "FC Barcelona": 131, "FC Bayern München": 27, "FC Bologna": 1025, "FC Brügge": 2282, "FC Girona": 12321,
    "FC Liverpool": 31, "FC Red Bull Salzburg": 409, "Feyenoord Rotterdam": 234, "Inter Mailand": 46,
    "Juventus Turin": 506, "Manchester City": 281, "OSC Lille": 1082, "Lille OSC": 1082, "PSV Eindhoven": 383,
    "Paris St. Germain": 583, "Paris Saint-Germain": 583, "RB Leipzig": 23826, "Real Madrid": 418,
    "Roter Stern Belgrad": 159, "Schachtjor Donezk": 660, "Shakhtar Donetsk": 660, "Slovan Bratislava": 540,
    "Sparta Prag": 197, "Sporting CP": 336, "Stade Brest": 3911, "Sturm Graz": 122, "VfB Stuttgart": 79,
    "Ajax Amsterdam": 610, "Athletic Club": 621, "Chelsea FC": 631, "Eintracht Frankfurt": 24,
    "FC Kopenhagen": 190, "FC Villareal": 1050, "Villarreal CF": 1050, "FK Bodö/Glimt": 501,
    "FK Kairat": 10482, "Galatasaray Istanbul": 141, "Newcastle United FC": 762, "Olympiakos Piräus": 683,
    "Olympique Marseille": 244, "Paphos FC": 45457, "Qarabag FK": 10625, "SSC Neapel": 6195,
    "SSC Napoli": 6195, "Slavia Prag": 62, "Tottenham Hotspur": 148, "Tottenham Hotspur FC": 148,
    "Union Saint-Gilloise": 3948, "AEK Athen": 2441, "AS Rom": 12, "Como 1907": 1047, "FC Porto": 720,
    "Fenerbahçe SK": 36, "LASK": 413, "Manchester United FC": 985, "RC Lens": 826, "Real Betis": 150,
    "Sabah": 63993, "Viking": 239, "AZ Alkmaar": 1090, "Besiktas Istanbul": 114, "Dynamo Kiew": 338,
    "FC Midtjylland": 865, "FC Twente Enschede": 317, "FCSB Bukarest": 301, "Ferencváros Budapest": 279,
    "Glasgow Rangers": 124, "IF Elfsborg": 1101, "Lazio Rom": 398, "Ludogorez Rasgrad": 31614,
    "Maccabi Tel Aviv": 119, "Malmö FF": 496, "OGC Nizza": 417, "Olympique Lyon": 1041,
    "PAOK Saloniki": 1091, "RSC Anderlecht": 58, "Real Sociedad": 681, "Rigas Futbola Skola": 33783,
    "Sporting Braga": 1075, "TSG Hoffenheim": 533, "Viktoria Pilsen": 941,
}

# Transfermarkt-Namen, die sich nicht automatisch einem football-data-Namen zuordnen lassen
TM_TO_FD: dict[str, str] = {
    "Nottingham Forest": "Nott'm Forest", "Wolverhampton Wanderers": "Wolves", "Rayo Vallecano": "Vallecano",
    "RCD Espanyol Barcelona": "Espanol", "Celta Vigo": "Celta", "Borussia Mönchengladbach": "M'gladbach",
    "1.FC Köln": "FC Koln", "Paris FC": "Paris FC", "Hellas Verona": "Verona",
    "Fortuna Sittard": "For Sittard", "NEC Nijmegen": "Nijmegen", "PEC Zwolle": "Zwolle",
    "Vitória Guimarães SC": "Guimaraes", "Estrela Amadora": "Estrela",
    "KV Mechelen": "Mechelen", "Sint-Truidense VV": "St Truiden", "Zulte Waregem": "Waregem",
    "Standard Lüttich": "Standard", "RAAL La Louvière": "RAAL La Louviere",
    "Basaksehir FK": "Buyuksehyr", "Göztepe": "Goztep", "Fatih Karagümrük": "Karagumruk",
    "Heart of Midlothian FC": "Hearts", "Hibernian FC": "Hibernian",
    "Rapid Wien": "SK Rapid", "Austria Wien": "Austria Vienna", "WSG Tirol": "Tirol",
    "Blau-Weiß Linz": "BW Linz", "SCR Altach": "Altach",
    "FC Zürich": "Zurich", "Grasshopper Club Zürich": "Grasshoppers",
    "Bröndby IF": "Brondby", "AGF Aarhus": "Aarhus", "Odense Boldklub": "Odense",
    "Sønderjyske Fodbold": "Sonderjyske", "Randers FC": "Randers FC",
    "Vålerenga Fotball": "Valerenga", "Lillestrøm SK": "Lillestrom", "Tromsø IL": "Tromso",
    "Strømsgodset IF": "Stromsgodset", "IFK Göteborg": "Goteborg", "BK Häcken": "Hacken",
    "Mjällby AIF": "Mjallby", "IFK Norrköping": "Norrkoping", "Örgryte IS": "Orgryte", "Östers IF": "Oster",
    "Legia Warschau": "Legia", "Rakow Czestochowa": "Rakow", "Wisla Krakau": "Wisla",
    "Universitatea Craiova": "Univ. Craiova", "Universitatea Cluj": "U. Cluj",
}

COMMON = {"fc", "sc", "ac", "as", "cf", "sk", "fk", "afc", "cd", "ss", "ssc", "ud", "rc", "rcd", "sv", "vfb",
          "vfl", "tsg", "if", "bk", "ik", "fk", "club", "de", "ca", "sd", "kv", "krc", "kaa", "rsc", "us", "uc",
          "1", "04", "05", "1899", "1907", "1909", "afc", "hsc", "osc", "ogc", "losc", "stade", "real", "nk"}


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t not in COMMON)


class EuTeams:
    """Löst Namen der Quellen in eu_team-IDs auf und legt Ligateams bei Bedarf an."""

    def __init__(self, session: Session):
        self.session = session
        self.by_alias = {(a.source, a.alias): a.team_id for a in session.scalars(select(EuTeamAlias))}
        self.by_tm = {t.tm_id: t.id for t in session.scalars(select(EuTeam).where(EuTeam.tm_id.is_not(None)))}
        for tm_id, (country, fd_name, display) in CLUBS.items():
            team_id = self.by_tm.get(tm_id)
            if team_id is None:
                team = EuTeam(name=display, country=country, tm_id=tm_id)
                session.add(team)
                session.flush()
                team_id = self.by_tm[tm_id] = team.id
            if fd_name:
                self._alias(f"fd:{country}", fd_name, team_id)
        for name, tm_id in OLDB_NAMES.items():
            self._alias("oldb", name, self.by_tm[tm_id])

    def _alias(self, source: str, alias: str, team_id: int) -> None:
        if (source, alias) not in self.by_alias:
            self.session.add(EuTeamAlias(team_id=team_id, source=source, alias=alias))
            self.by_alias[(source, alias)] = team_id

    def fd(self, country: str, name: str) -> int:
        key = (f"fd:{country}", name)
        if key not in self.by_alias:
            team = EuTeam(name=name, country=country)
            self.session.add(team)
            self.session.flush()
            self._alias(*key, team.id)
        return self.by_alias[key]

    def oldb(self, name: str) -> int:
        team_id = self.by_alias.get(("oldb", name.strip()))
        if team_id is None:
            raise ValueError(f"Unbekannter Europapokal-Verein bei OpenLigaDB: {name!r}. In ingest/europe.py "
                             "unter OLDB_NAMES (und CLUBS) eintragen.")
        return team_id

    def tm(self, country: str, tm_id: int, tm_name: str) -> int | None:
        """Transfermarkt-Verein einem Team zuordnen: Europapokal-Teilnehmer über die ID, sonst über den
        Namen innerhalb der Liga (football-data)."""
        if tm_id in self.by_tm:
            return self.by_tm[tm_id]
        if ("tm", str(tm_id)) in self.by_alias:
            return self.by_alias[("tm", str(tm_id))]
        candidates = {alias: tid for (src, alias), tid in self.by_alias.items() if src == f"fd:{country}"}
        if not candidates:
            return None
        if tm_name in TM_TO_FD and TM_TO_FD[tm_name] in candidates:
            team_id = candidates[TM_TO_FD[tm_name]]
        else:
            normed = {_norm(a): tid for a, tid in candidates.items()}
            target = _norm(tm_name)
            match = next((tid for n, tid in normed.items() if n and (n in target or target in n)), None)
            if match is None:
                close = difflib.get_close_matches(target, list(normed), n=1, cutoff=0.75)
                match = normed[close[0]] if close else None
            if match is None:
                return None
            team_id = match
        taken = {tid for (src, _), tid in self.by_alias.items() if src == "tm"} | set(self.by_tm.values())
        if team_id in taken:
            return None  # Team hat schon einen anderen Transfermarkt-Verein (unsichere Namensähnlichkeit)
        self._alias("tm", str(tm_id), team_id)
        return team_id


def _season_code(year: int) -> str:
    return f"{year % 100:02d}{(year + 1) % 100:02d}"


def _parse_fd_date(d: str, t: str | None) -> datetime:
    fmt = "%d/%m/%Y" if len(d.split("/")[-1]) == 4 else "%d/%m/%y"
    day = datetime.strptime(d, fmt)
    hh, mm = (t or "15:00").split(":")[:2] if t else ("15", "00")
    return day.replace(hour=int(hh), minute=int(mm), tzinfo=UK)


def _int(v: str | None) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except ValueError:
        return None


def ingest_domestic(session: Session, seasons: list[int]) -> int:
    """Ligaspiele (nur gespielte) der football-data-Ligen."""
    teams = EuTeams(session)
    rows = []
    for country in FD_MAIN:
        for year in seasons:
            past = year < max(seasons)
            try:
                text = get_text(f"https://www.football-data.co.uk/mmz4281/{_season_code(year)}/{country}.csv",
                                cache=past)
            except Exception:
                continue  # Saison noch nicht angelegt
            for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
                hg, ag = _int(r.get("FTHG")), _int(r.get("FTAG"))
                if not r.get("HomeTeam") or hg is None:
                    continue
                rows.append(_domestic_row(teams, country, year, r["Date"], r.get("Time"), r["HomeTeam"], r["AwayTeam"], hg, ag))
    start = date(min(seasons), 7, 1)
    for country in FD_EXTRA:
        text = get_text(f"https://www.football-data.co.uk/new/{country}.csv")
        for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
            hg, ag = _int(r.get("HG")), _int(r.get("AG"))
            if hg is None or not r.get("Home"):
                continue
            kickoff = _parse_fd_date(r["Date"], r.get("Time"))
            if kickoff.date() < start:
                continue
            year = int(r["Season"].split("/")[0])
            rows.append(_domestic_row(teams, country, year, r["Date"], r.get("Time"), r["Home"], r["Away"], hg, ag))
    upsert(session, EuMatch, rows, ["competition", "source_id"])
    return len(rows)


def _domestic_row(teams: EuTeams, country: str, year: int, d: str, t: str | None, home: str, away: str,
                  hg: int, ag: int) -> dict:
    kickoff = _parse_fd_date(d, t)
    return {"competition": country, "season": year, "kickoff": kickoff,
            "home_id": teams.fd(country, home), "away_id": teams.fd(country, away),
            "home_goals": hg, "away_goals": ag, "finished": True, "neutral": False,
            "source_id": f"{kickoff:%Y-%m-%d}|{home}|{away}"}


def _result(m: dict) -> tuple[int | None, int | None]:
    for r in m.get("matchResults") or []:
        if r["resultTypeID"] == 2:
            return r["pointsTeam1"], r["pointsTeam2"]
    return None, None


def ingest_euro(session: Session, competitions=EURO_COMPETITIONS) -> int:
    """Europapokal-Spiele inkl. Spielplan der laufenden Saison."""
    teams = EuTeams(session)
    rows = []
    for comp, code, year in competitions:
        data = get_json(f"https://api.openligadb.de/getmatchdata/{code}/{year}")
        for m in data:
            hg, ag = _result(m)
            finished = bool(m["matchIsFinished"]) and hg is not None
            round_name = re.sub(r"(\d)\.(\S)", r"\1. \2", m["group"]["groupName"]).strip()
            rows.append({
                "competition": comp, "season": year, "round_no": m["group"]["groupOrderID"],
                "round_name": round_name,
                "kickoff": datetime.fromisoformat(m["matchDateTimeUTC"].replace("Z", "+00:00")),
                "home_id": teams.oldb(m["team1"]["teamName"]), "away_id": teams.oldb(m["team2"]["teamName"]),
                "home_goals": hg if finished else None, "away_goals": ag if finished else None,
                "finished": finished, "neutral": round_name.lower().startswith(("finale", "endspiel")),
                "source_id": str(m["matchID"]),
            })
    upsert(session, EuMatch, rows, ["competition", "source_id"])
    return len(rows)


VALUE_URL = "https://www.transfermarkt.de/x/marktwerteverein/wettbewerb/{liga}/stichtag/{stichtag}"


def value_stichtage(start: date, end: date | None = None) -> list[date]:
    """Quartalsweise Stichtage (erster angebotener Tag im Januar, April, Juli, Oktober) plus der neueste."""
    end = end or date.today()
    available = [d for d in available_stichtage() if start <= d <= end]
    out = []
    for d in available:
        if d.month in (1, 4, 7, 10) and not any(o.year == d.year and o.month == d.month for o in out):
            out.append(d)
    if available and available[-1] not in out:
        out.append(available[-1])
    return out


def ingest_values(session: Session, start: date = date(FIRST_SEASON, 7, 1), end: date | None = None,
                  log=print) -> tuple[int, dict[str, list[str]]]:
    """Kaderwerte aller Vereine der Ligen in TM_LEAGUE zu den Stichtagen. Liefert (Anzahl, nicht
    zugeordnete Vereine je Liga). Nicht zugeordnet bleiben vor allem Vereine kleiner Länder, die nie im
    Europapokal waren; sie werden nicht gebraucht."""
    teams = EuTeams(session)
    rows, unknown = [], {}
    days = value_stichtage(start, end)
    for d in days:
        historic = d < date.today().replace(day=1)
        for country, liga in TM_LEAGUE.items():
            html = get_text(VALUE_URL.format(liga=liga, stichtag=d.isoformat()), headers=BROWSER_HEADERS,
                            cache=historic, delay=2.0)  # Pause nur nach echten Abrufen, nicht aus dem Cache
            table = BeautifulSoup(html, "html.parser").select("table.items")
            if not table:
                continue
            for tr in table[0].select("tbody > tr"):
                link = tr.select_one("td.hauptlink a")
                cells = tr.find_all("td", recursive=False)
                if not link or len(cells) < 5:
                    continue
                m = re.search(r"/verein/(\d+)", link["href"])
                value = parse_value(cells[4].get_text(strip=True))
                if not m or not value:
                    continue
                team_id = teams.tm(country, int(m.group(1)), link.get("title") or link.get_text(strip=True))
                if team_id is None:
                    unknown.setdefault(country, set()).add(link.get("title") or link.get_text(strip=True))
                    continue
                rows.append({"team_id": team_id, "stichtag": d, "value_eur": value})
        # je Stichtag speichern, damit ein Abbruch (Transfermarkt-Sperre) nichts verliert
        day_rows = {r["team_id"]: r for r in rows if r["stichtag"] == d}  # ein Verein kann in zwei Ligen stehen
        upsert(session, EuSquadValue, list(day_rows.values()), ["team_id", "stichtag"])
        session.commit()
        log(f"  Kaderwerte {d:%d.%m.%Y}: {len(rows)} bisher")
    return len(rows), {k: sorted(v) for k, v in unknown.items()}



# Kurznamen für enge Stellen (Spielkarten); sonst der Anzeigename
SHORT = {
    "Manchester City": "Man City", "Manchester United": "Man United", "Tottenham Hotspur": "Tottenham",
    "Newcastle United": "Newcastle", "Atlético Madrid": "Atlético", "Athletic Bilbao": "Bilbao",
    "Paris Saint-Germain": "Paris SG", "Olympique Marseille": "Marseille", "Olympique Lyon": "Lyon",
    "Inter Mailand": "Inter", "Juventus Turin": "Juventus", "Atalanta Bergamo": "Atalanta",
    "Benfica Lissabon": "Benfica", "Sporting Lissabon": "Sporting", "Sporting Braga": "Braga",
    "Feyenoord Rotterdam": "Feyenoord", "Ajax Amsterdam": "Ajax", "Union Saint-Gilloise": "Union SG",
    "Olympiakos Piräus": "Olympiakos", "PAOK Saloniki": "PAOK", "Celtic Glasgow": "Celtic",
    "Glasgow Rangers": "Rangers", "Young Boys Bern": "Young Boys", "FC Kopenhagen": "Kopenhagen",
    "Viking Stavanger": "Viking", "Roter Stern Belgrad": "Roter Stern", "Schachtar Donezk": "Schachtar",
    "Slovan Bratislava": "Slovan", "Qarabağ Ağdam": "Qarabağ", "Kairat Almaty": "Kairat",
    "Ludogorez Rasgrad": "Ludogorez", "Maccabi Tel Aviv": "Maccabi TA", "Viktoria Pilsen": "Pilsen",
    "Eintracht Frankfurt": "Frankfurt", "Borussia Dortmund": "Dortmund", "FC Bayern München": "Bayern",
    "Bayer 04 Leverkusen": "Leverkusen", "VfB Stuttgart": "Stuttgart", "TSG Hoffenheim": "Hoffenheim",
    "Real Sociedad": "Sociedad", "RSC Anderlecht": "Anderlecht", "Dinamo Zagreb": "Dinamo Zagreb",
    "FC Chelsea": "Chelsea", "FC Liverpool": "Liverpool", "FC Arsenal": "Arsenal", "FC Barcelona": "Barcelona",
    "FC Villarreal": "Villarreal", "FC Brügge": "Brügge", "FC Bologna": "Bologna", "FC Girona": "Girona",
    "OSC Lille": "Lille", "Stade Brest": "Brest", "OGC Nizza": "Nizza", "AS Monaco": "Monaco",
    "Lazio Rom": "Lazio", "SSC Neapel": "Neapel", "Olympiakos Piräus": "Olympiakos",
}
EU_TEAM_INFO = "web/src/lib/eu_teams.json"
EU_LOGO_DIR = "web/public/logos/eu"


def ingest_logos(session: Session, force: bool = False) -> dict:
    """Wappen der Europapokal-Teams (Transfermarkt) nach web/public/logos/eu/<tm_id>.png und Name ->
    {logo, short} nach web/src/lib/eu_teams.json (getrennt von teams.json der Bundesliga)."""
    import json

    from fussballdb.config import ROOT
    from fussballdb.ingest.http import _client
    from fussballdb.ingest.logos import TM_URL, _image_ext

    logo_dir = ROOT / EU_LOGO_DIR
    logo_dir.mkdir(parents=True, exist_ok=True)
    info, loaded, missing = {}, 0, []
    for team in session.scalars(select(EuTeam).where(EuTeam.tm_id.is_not(None)).order_by(EuTeam.name)):
        path = logo_dir / f"{team.tm_id}.png"
        if force or not path.exists():
            try:
                resp = _client.get(TM_URL.format(id=team.tm_id), headers=BROWSER_HEADERS)
                resp.raise_for_status()
                if _image_ext(resp.content) == ".png":
                    path.write_bytes(resp.content)
                    loaded += 1
            except Exception:
                pass
        if not path.exists():
            missing.append(team.name)
        info[team.name] = {"logo": f"/logos/eu/{path.name}" if path.exists() else None,
                           "short": SHORT.get(team.name, team.name)}
    (ROOT / EU_TEAM_INFO).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    return {"geladen": loaded, "fehlen": missing}
