"""Kicktipp-Tipprunden: Punkteregel und Bonusfragen von den öffentlichen Seiten einer Runde
(kicktipp.de/<runde>/spielregeln und /<runde>/tippuebersicht?bonus=true). Kicktipp hat keine offizielle
Schnittstelle; gelesen werden nur diese beiden Seiten, ohne Anmeldung. Private Runden zeigen die Regeln nicht
öffentlich, dann wird die Regel von Hand eingetragen."""

import html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fussballdb.db.models import TipRound
from fussballdb.ingest.http import get_text

BASE = "https://www.kicktipp.de/{slug}/{page}"


def slug_from_url(url_or_slug: str) -> str:
    """"https://www.kicktipp.de/waschndalos/" oder "waschndalos" -> "waschndalos"."""
    m = re.search(r"kicktipp\.[a-z]+/([A-Za-z0-9_-]+)", url_or_slug)
    slug = m.group(1) if m else url_or_slug.strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,80}", slug):
        raise ValueError(f"Keine Kicktipp-Runde erkannt: {url_or_slug!r}")
    return slug


def _text(page: str) -> str:
    page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return re.sub(r"\n\s*\n+", "\n", html.unescape(re.sub(r"<[^>]+>", "\n", page)))


def parse_rules(page: str) -> dict:
    """Punkteregel (Sieg Tendenz, Sieg Tordifferenz, exakt, Remis Tendenz), Tippschluss und Bonuspunkte."""
    text = _text(page)
    if "genaue Ergebnis" not in text:
        raise ValueError("Diese Tipprunde tippt nicht das genaue Ergebnis; das wird nicht unterstützt.")
    m = re.search(r"Tendenz\s+Tordifferenz\s+Ergebnis\s+Sieg\s+(\d+)\s+(\d+)\s+(\d+)\s+Unentschieden\s+(\d+)\s+-\s+(\d+)",
                  text)
    if not m:
        raise ValueError("Punkteregel nicht gefunden (Runde privat oder andere Regel, z. B. Punkte nach Quote).")
    win_t, win_d, exact, draw_t, draw_exact = map(int, m.groups())
    lead = re.search(r"Tippzeit endet (\d+) Minuten vor", text)
    bonus = re.search(r"Punkte pro richtiger Antwort:\s*(\d+)", text)
    return {"win_tendency": win_t, "win_diff": win_d, "exact": max(exact, draw_exact), "draw_tendency": draw_t,
            "lead_minutes": int(lead.group(1)) if lead else None,
            "bonus_points": int(bonus.group(1)) if bonus and int(bonus.group(1)) > 0 else None}


def bonus_questions(slug: str) -> list[dict]:
    """Bonusfragen der Runde: Termin, Frage, Abkürzung und (falls schon entschieden) die Antworten."""
    text = _text(get_text(BASE.format(slug=slug, page="tippuebersicht?bonus=true")))
    out = []
    for m in re.finditer(r"(\d\d\.\d\d\.\d\d \d\d:\d\d)\n([^\n]+\?)\n([^\n]+)\n((?:[^\n]+\n)*?)(?=\d\d\.\d\d\.\d\d \d\d:\d\d|Pos\n)",
                         text):
        answers = [a for a in m.group(4).split("\n") if a and a != "---"]
        out.append({"termin": m.group(1), "frage": m.group(2).strip(), "kurz": m.group(3).strip(),
                    "antworten": answers[: len(answers) // 2] if answers else []})  # Name und Kürzel je Antwort
    return out


def add_round(session: Session, url_or_slug: str, name: str | None = None) -> TipRound:
    """Tipprunde anlegen oder ihre Regel neu lesen."""
    slug = slug_from_url(url_or_slug)
    rules = parse_rules(get_text(BASE.format(slug=slug, page="spielregeln")))
    rnd = session.scalar(select(TipRound).where(TipRound.slug == slug))
    if rnd is None:
        rnd = TipRound(slug=slug, name=name or slug, is_default=session.scalar(select(TipRound.id).limit(1)) is None)
        session.add(rnd)
    for k, v in rules.items():
        setattr(rnd, k, v)
    rnd.url = BASE.format(slug=slug, page="")
    rnd.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return rnd


def _schedule(slug: str, matchday: int) -> list[tuple[datetime, str, str]] | None:
    """Spiele eines Spieltags in der Reihenfolge des Kicktipp-Spielplans (Anstoß, Heim, Gast); None, wenn die
    Seite der Runde nicht öffentlich ist (Weiterleitung zum Login)."""
    page = get_text(BASE.format(slug=slug, page=f"tippspielplan?spieltagIndex={matchday}"))
    if "profil/login" in page[:5000] and "tippspielplan" not in page[:5000]:
        return None
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        date = r"\d\d\.\d\d\.\d\d \d\d:\d\d"
        if len(cells) >= 3 and re.match(date, cells[0]):
            when = datetime.strptime(cells[0][:14], "%d.%m.%y %H:%M").replace(tzinfo=ZoneInfo("Europe/Berlin"))
            teams = [c for c in cells[1:] if c and not re.match(date, c)]  # danach evtl. Tippschluss
            if len(teams) >= 2:
                rows.append((when, teams[0], teams[1]))
    return rows or None


def ingest_order(session: Session, season: int, matchdays: list[int]) -> dict:
    """Reihenfolge der Spiele je Spieltag wie bei Kicktipp (alle Bundesliga-Runden haben denselben Spielplan)
    aus der ersten Tipprunde mit öffentlichem Spielplan; gespeichert als match.kicktipp_pos."""
    from fussballdb.ingest.tv import _similarity

    slugs = list(session.scalars(select(TipRound.slug).order_by(TipRound.is_default.desc(), TipRound.id)))
    games = session.execute(text("""
        SELECT m.id, m.matchday, m.kickoff,
               string_agg(DISTINCT ha.alias, '|') || '|' || ht.name, string_agg(DISTINCT aa.alias, '|') || '|' || at.name
        FROM match m JOIN season s ON s.id = m.season_id
        JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
        LEFT JOIN team_alias ha ON ha.team_id = ht.id LEFT JOIN team_alias aa ON aa.team_id = at.id
        WHERE s.start_year = :y AND m.matchday = ANY(:md)
        GROUP BY m.id, m.matchday, m.kickoff, ht.name, at.name"""), {"y": season, "md": matchdays}).all()
    updated, missing = 0, []
    for md in matchdays:
        schedule = next((s for s in (_schedule(slug, md) for slug in slugs) if s), None)
        if not schedule:
            missing.append(md)
            continue
        ours = [g for g in games if g[1] == md]
        for pos, (_, home, away) in enumerate(schedule, 1):
            best = max(ours, key=lambda g: _similarity(home, g[3]) + _similarity(away, g[4]), default=None)
            if best is not None and _similarity(home, best[3]) + _similarity(away, best[4]) >= 1.2:
                session.execute(text("UPDATE match SET kicktipp_pos = :p WHERE id = :id"), {"p": pos, "id": best[0]})
                ours = [g for g in ours if g[0] != best[0]]
                updated += 1
    return {"spiele": updated, "ohne_spielplan": missing}
