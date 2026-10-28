"""Brasilianische Série A (Wettbewerb "BRA" in eu_match, Saison = Kalenderjahr).

- Ergebnisse 2012 bis 2022 von football-data.co.uk (new/BRA.csv): nur als Vorgeschichte für die Elo.
- Ab 2023 ist FotMob die einzige Quelle für Spielplan, Spieltag, Ergebnis und xG (Liga 268). Zwei Quellen für
  dieselben Spiele würden doppelte Spiele erzeugen. Die Teams werden über die Spiele 2023 bis heute, die in
  beiden Quellen stehen, den football-data-Namen zugeordnet (gleiches Datum ±1 Tag, ähnliche Namen), damit
  die Elo über den Quellenwechsel hinweg dasselbe Team weiterführt.
- Schlussquoten von football-data (Durchschnitt aller Buchmacher) liefert market_probs() für den
  Rückblick-Test gegen den Wettmarkt.
- Kaderwerte kommen mit ingest/europe.py (Transfermarkt BRA1).

Brasilien spielt nie gegen europäische Teams; model/europe.py rechnet die Liga deshalb als eigene Welt.
"""

import csv
import difflib
import io
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.models import EuMatch
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.cl_xg import _next_data, match_xg
from fussballdb.ingest.europe import EuTeams, _norm, _parse_fd_date
from fussballdb.ingest.http import get_text
from fussballdb.ingest.upsert import upsert

COMP = "BRA"
FD_URL = "https://www.football-data.co.uk/new/BRA.csv"
FOTMOB_FIXTURES = "https://www.fotmob.com/leagues/268/fixtures/serie-a?season={season}"
FOTMOB_FROM = 2023  # ab hier FotMob (mit xG); davor football-data
FIRST_SEASON = 2012


def fd_rows() -> list[dict]:
    """Alle Spiele aus football-data (Ergebnis, Schlussquoten), Anstoß in britischer Zeit wie bei allen Ligen."""
    out = []
    for r in csv.DictReader(io.StringIO(get_text(FD_URL).lstrip("﻿"))):
        if not r.get("Home") or r.get("HG") in (None, ""):
            continue
        out.append({"season": int(r["Season"]), "kickoff": _parse_fd_date(r["Date"], r.get("Time")),
                    "home": r["Home"], "away": r["Away"], "hg": int(float(r["HG"])), "ag": int(float(r["AG"])),
                    "odds": tuple(float(r[k]) if r.get(k) else None for k in ("AvgCH", "AvgCD", "AvgCA"))})
    return out


def fotmob_fixtures(season: int) -> list[dict]:
    html = get_text(FOTMOB_FIXTURES.format(season=season), headers=BROWSER_HEADERS, cache=season < datetime.now().year)
    out = []
    for m in _next_data(html).get("fixtures", {}).get("allMatches", []):
        st = m.get("status", {})
        if not st.get("utcTime"):
            continue
        postponed = (st.get("reason") or {}).get("short") == "PP"
        if st.get("cancelled") and not postponed:
            continue  # abgesagt
        score = st.get("scoreStr") if st.get("finished") else None
        hg, ag = (int(x) for x in score.split(" - ")) if score else (None, None)
        out.append({"id": int(m["id"]), "round": int(m.get("round") or 0), "home": m["home"]["name"],
                    "away": m["away"]["name"], "home_fm": m["home"]["id"], "away_fm": m["away"]["id"],
                    "kickoff": datetime.fromisoformat(st["utcTime"].replace("Z", "+00:00")),
                    "finished": bool(st.get("finished")), "hg": hg, "ag": ag})
    return out


def _learn_aliases(fm: list[dict], fd: list[dict]) -> dict[str, str]:
    """FotMob-Team-ID -> football-data-Name: je gespieltem FotMob-Spiel das football-data-Spiel am selben Tag
    (±1) mit den ähnlichsten Namen; je Team gewinnt der häufigste Treffer."""
    by_day: dict = {}
    for r in fd:
        by_day.setdefault(r["kickoff"].date(), []).append(r)
    votes: dict[str, Counter] = {}
    sim = lambda a, b: difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()  # noqa: E731
    for m in fm:
        if not m["finished"]:
            continue
        day = m["kickoff"].date()
        cands = [r for d in (day - timedelta(days=1), day, day + timedelta(days=1)) for r in by_day.get(d, [])
                 if (r["hg"], r["ag"]) == (m["hg"], m["ag"])]
        best = max(cands, key=lambda r: sim(m["home"], r["home"]) + sim(m["away"], r["away"]), default=None)
        if best and sim(m["home"], best["home"]) + sim(m["away"], best["away"]) >= 0.8:
            votes.setdefault(m["home_fm"], Counter())[best["home"]] += 1
            votes.setdefault(m["away_fm"], Counter())[best["away"]] += 1
    return {team: c.most_common(1)[0][0] for team, c in votes.items()}


def ingest(session: Session, seasons: list[int] | None = None, log=print) -> dict:
    """Spiele laden: football-data bis 2022, FotMob ab 2023 (inklusive offener Spiele der laufenden Saison).
    Danach xG der gespielten FotMob-Spiele ohne xG nachtragen (eine Seite je Spiel, gespielte aus dem Cache)."""
    now = datetime.now()
    seasons = seasons or list(range(FIRST_SEASON, now.year + 1))
    teams = EuTeams(session)
    fd = fd_rows()
    rows = []
    for r in fd:
        if r["season"] < FOTMOB_FROM and r["season"] in seasons:
            rows.append({"competition": COMP, "season": r["season"], "round_no": 0, "round_name": None,
                         "kickoff": r["kickoff"], "home_id": teams.fd(COMP, r["home"]), "away_id": teams.fd(COMP, r["away"]),
                         "home_goals": r["hg"], "away_goals": r["ag"], "finished": True, "neutral": False,
                         "source_id": f"fd:{r['kickoff']:%Y-%m-%d}|{r['home']}|{r['away']}", "fotmob_id": None})
    fm_seasons = [s for s in seasons if s >= FOTMOB_FROM]
    fm = {s: fotmob_fixtures(s) for s in fm_seasons}
    aliases = _learn_aliases([m for s in fm.values() for m in s], [r for r in fd if r["season"] >= FOTMOB_FROM])
    unmapped, names = set(), {}
    for season, matches in fm.items():
        for m in matches:
            ids = []
            for side in ("home", "away"):
                fd_name = aliases.get(m[f"{side}_fm"])
                if fd_name is None:
                    unmapped.add(m[side])
                    fd_name = m[side]  # neues Team ohne football-data-Spiel: FotMob-Name
                ids.append(teams.fd(COMP, fd_name))
            rows.append({"competition": COMP, "season": season, "round_no": m["round"], "round_name": f"{m['round']}. Spieltag",
                         "kickoff": m["kickoff"], "home_id": ids[0], "away_id": ids[1], "home_goals": m["hg"],
                         "away_goals": m["ag"], "finished": m["finished"], "neutral": False,
                         "source_id": f"fm:{m['id']}", "fotmob_id": m["id"]})
            for side, tid in zip(("home", "away"), ids):
                teams._alias("fm:BRA", m[side], tid)
                teams._alias("fmid:BRA", str(m[f"{side}_fm"]), tid)  # FotMob-Team-ID (Wappen, ingest_logos)
                names[tid] = m[side]
    upsert(session, EuMatch, rows, ["competition", "source_id"])
    for tid, name in names.items():  # Anzeige mit FotMob-Namen ("São Paulo" statt "Sao Paulo", "Flamengo" statt "Flamengo RJ")
        session.execute(text("UPDATE eu_team SET name = :n WHERE id = :id AND tm_id IS NULL"), {"n": name, "id": tid})
    session.commit()
    log(f"  {len(rows)} Spiele, nicht zugeordnet: {sorted(unmapped) or 'keine'}")
    return {"spiele": len(rows), "xg": ingest_xg(session, log=log), "nicht_zugeordnet": sorted(unmapped)}


def ingest_xg(session: Session, log=print) -> int:
    """xG gespielter FotMob-Spiele ohne xG (eine Seite je Spiel)."""
    todo = session.execute(text("""SELECT id, fotmob_id FROM eu_match WHERE competition = :c AND finished
                                   AND home_xg IS NULL AND fotmob_id IS NOT NULL ORDER BY kickoff"""), {"c": COMP}).all()
    n = 0
    for i, (match_id, fotmob_id) in enumerate(todo, 1):
        xg = match_xg(fotmob_id)
        if xg:
            session.execute(text("UPDATE eu_match SET home_xg = :h, away_xg = :a WHERE id = :id"),
                            {"h": xg[0], "a": xg[1], "id": match_id})
            n += 1
        if i % 100 == 0:
            session.commit()
            log(f"  xG {i}/{len(todo)}")
    session.commit()
    return n


def market_probs() -> dict[tuple, tuple[float, float, float]]:
    """(Saison, Heim, Gast) mit football-data-Namen -> Wahrscheinlichkeiten aus den Schlussquoten (Durchschnitt aller
    Buchmacher, Marge entfernt). Jede Paarung gibt es je Saison einmal; das Datum weicht zwischen den Quellen
    teils um einen Tag ab (britische Zeit bei football-data)."""
    out = {}
    for r in fd_rows():
        if None in r["odds"]:
            continue
        inv = [1 / o for o in r["odds"]]
        s = sum(inv)
        out[(r["season"], r["home"], r["away"])] = tuple(x / s for x in inv)
    return out
