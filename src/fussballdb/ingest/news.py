"""Nachrichten je Bundesliga-Verein aus Google News (RSS), mit Lokalzeitungen markiert.

Je Verein eine Suche der letzten Tage (deutsch); gespeichert werden nur Überschrift, Quelle, Datum und Link,
keine Artikeltexte (viele stehen hinter einer Bezahlschranke, fremde Texte werden nicht kopiert). Lokal sind
Meldungen aus den Zeitungen und Sendern der Region (LOCAL), "Verein" die vom Verein selbst.

Google erlaubt den Feed nur für den persönlichen, nicht kommerziellen Gebrauch in einem Feedreader. Für eine
öffentliche App bräuchte es direkte RSS-Feeds der Zeitungen.

Überschriften bekommen ein Embedding (LM Studio wie bei den Spielberichten), damit Chat und MCP nach Bedeutung
suchen können; ohne LM Studio bleibt die Volltextsuche.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.http import get_text

FEED = "https://news.google.com/rss/search?q={q}+when:{days}d&hl=de&gl=DE&ceid=DE:de"

# Suchbegriffe je Verein (unser Name -> wie die Presse ihn schreibt)
QUERY = {
    "FC Bayern München": ['"FC Bayern"'], "Borussia Dortmund": ['"Borussia Dortmund"', "BVB"],
    "Bayer 04 Leverkusen": ['"Bayer Leverkusen"'], "RB Leipzig": ['"RB Leipzig"'],
    "Eintracht Frankfurt": ['"Eintracht Frankfurt"'], "VfB Stuttgart": ['"VfB Stuttgart"'],
    "SC Freiburg": ['"SC Freiburg"'], "Borussia Mönchengladbach": ['"Borussia Mönchengladbach"', "Gladbach"],
    "1. FC Köln": ['"1. FC Köln"', '"FC Köln"'], "1. FSV Mainz 05": ['"Mainz 05"'],
    "SV Werder Bremen": ['"Werder Bremen"'], "1. FC Union Berlin": ['"Union Berlin"'],
    "TSG Hoffenheim": ['"TSG Hoffenheim"'], "FC Augsburg": ['"FC Augsburg"'], "Hamburger SV": ['"Hamburger SV"'],
    "FC Schalke 04": ['"Schalke 04"'], "SV 07 Elversberg": ['"SV Elversberg"'], "SC Paderborn 07": ['"SC Paderborn"'],
    "VfL Wolfsburg": ['"VfL Wolfsburg"'], "FC St. Pauli": ['"FC St. Pauli"'], "1. FC Heidenheim 1846": ['"1. FC Heidenheim"'],
    "VfL Bochum": ['"VfL Bochum"'], "Holstein Kiel": ['"Holstein Kiel"'], "Hertha BSC": ['"Hertha BSC"'],
    "Fortuna Düsseldorf": ['"Fortuna Düsseldorf"'], "Hannover 96": ['"Hannover 96"'],
    "1. FC Nürnberg": ['"1. FC Nürnberg"'], "DSC Arminia Bielefeld": ['"Arminia Bielefeld"'],
    "SV Darmstadt 98": ['"Darmstadt 98"'],
}

# Zeitungen und Sender der Region je Verein (Domain der Quelle laut Google News)
LOCAL = {
    "FC Bayern München": ("tz.de", "merkur.de", "abendzeitung-muenchen.de", "sueddeutsche.de", "br.de"),
    "Borussia Dortmund": ("ruhrnachrichten.de", "waz.de", "wa.de", "wdr.de", "reviersport.de"),
    "Bayer 04 Leverkusen": ("ksta.de", "rp-online.de", "wdr.de"),
    "RB Leipzig": ("lvz.de", "mdr.de", "l-iz.de", "rblive.de", "tag24.de"),
    "Eintracht Frankfurt": ("fr.de", "fnp.de", "hessenschau.de", "faz.net", "op-online.de"),
    "VfB Stuttgart": ("stuttgarter-nachrichten.de", "stuttgarter-zeitung.de", "zvw.de", "swr.de", "swp.de"),
    "SC Freiburg": ("badische-zeitung.de", "swr.de", "baden.fm"),
    "Borussia Mönchengladbach": ("rp-online.de", "wz.de", "wdr.de"),
    "1. FC Köln": ("ksta.de", "express.de", "rundschau-online.de", "wdr.de", "koeln.de", "geissblog.koeln"),
    "1. FSV Mainz 05": ("allgemeine-zeitung.de", "swr.de", "merkurist.de"),
    "SV Werder Bremen": ("weser-kurier.de", "butenunbinnen.de", "kreiszeitung.de", "deichstube.de", "ndr.de"),
    "1. FC Union Berlin": ("tagesspiegel.de", "bz-berlin.de", "rbb24.de", "morgenpost.de", "berliner-zeitung.de"),
    "TSG Hoffenheim": ("rnz.de", "stimme.de", "swr.de", "mannheimer-morgen.de"),
    "FC Augsburg": ("augsburger-allgemeine.de", "br.de", "presse-augsburg.de"),
    "Hamburger SV": ("abendblatt.de", "mopo.de", "ndr.de"),
    "FC Schalke 04": ("waz.de", "ruhrnachrichten.de", "reviersport.de", "wdr.de", "derwesten.de"),
    "SV 07 Elversberg": ("sol.de", "sr.de", "saarbruecker-zeitung.de"),
    "SC Paderborn 07": ("nw.de", "westfalen-blatt.de", "wdr.de", "radiohochstift.de"),
    "VfL Wolfsburg": ("waz-online.de", "ndr.de", "wolfsburger-nachrichten.de"),
    "FC St. Pauli": ("abendblatt.de", "mopo.de", "ndr.de"),
    "1. FC Heidenheim 1846": ("hz.de", "swp.de", "swr.de"),
}
# Vereinsseiten: eigene Kennzeichnung "Verein"
CLUB = {"FC Bayern München": "fcbayern.com", "Borussia Dortmund": "bvb.de", "VfB Stuttgart": "vfb.de",
        "Eintracht Frankfurt": "eintracht.de", "1. FC Köln": "fc.de", "SV Werder Bremen": "werder.de",
        "Hamburger SV": "hsv.de", "FC Schalke 04": "schalke04.de", "Borussia Mönchengladbach": "borussia.de",
        "SC Freiburg": "scfreiburg.com", "1. FSV Mainz 05": "mainz05.de", "1. FC Union Berlin": "fc-union-berlin.de",
        "TSG Hoffenheim": "tsg-hoffenheim.de", "FC Augsburg": "fcaugsburg.de", "RB Leipzig": "rbleipzig.com",
        "Bayer 04 Leverkusen": "bayer04.de", "SV 07 Elversberg": "sv07elversberg.de", "SC Paderborn 07": "scp07.de"}
# Spam für illegale Livestreams ("[LIVE!#Ansehen]* FC Augsburg - … heute übertragung"): unsichtbare Zeichen und
# Sonderzeichen, die keine Zeitung in Überschriften verwendet
SPAM = re.compile(r"[\u200b-\u200f\u2060\ufeff]|[$@~>{}\[\]]")
# andere Sportarten und Teams des Vereins, die mit der Bundesliga-Mannschaft nichts zu tun haben
OFF_TOPIC = re.compile(r"\b(Handball|Basketball|Eishockey|Volleyball|Frauen|Juniorinnen|U\s?1[5-9]|U\s?2[0-3]|"
                       r"Nachwuchs|E-?Sports?|Futsal|Damen)\b", re.I)


def _domain(url: str | None) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host.removeprefix("www.")


def kind(team: str, source_url: str | None) -> str | None:
    """ "lokal", "verein" oder None (überregional)."""
    host = _domain(source_url)
    if host and CLUB.get(team) and (host == CLUB[team] or host.endswith("." + CLUB[team])):
        return "verein"
    if any(host == d or host.endswith("." + d) for d in LOCAL.get(team, ())):
        return "lokal"
    return None


def parse(xml: str, team: str) -> list[dict]:
    """Einträge eines Google-News-Feeds: Überschrift ohne angehängte Quelle, Link, Quelle, Datum, Art."""
    out = []
    for item in ET.fromstring(xml).iter("item"):
        title = (item.findtext("title") or "").strip()
        src = item.find("source")
        source = (src.text or "").strip() if src is not None else ""
        source_url = src.get("url") if src is not None else None
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        if not title or OFF_TOPIC.search(title) or SPAM.search(title):
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        out.append({"title": title, "link": item.findtext("link"), "source": source or None,
                    "source_url": source_url, "published_at": published, "kind": kind(team, source_url)})
    return out


def ingest(session: Session, days: int = 3, log=print) -> dict:
    """Meldungen der letzten `days` Tage für alle Vereine der laufenden Bundesliga-Saison."""
    teams = session.execute(text("""
        SELECT DISTINCT t.id, t.name FROM match m JOIN season s ON s.id = m.season_id
        JOIN team t ON t.id IN (m.home_team_id, m.away_team_id)
        WHERE s.start_year = (SELECT max(start_year) FROM season)""")).all()
    now = datetime.now(timezone.utc)
    n, per_team = 0, {}
    for team_id, name in teams:
        q = " OR ".join(QUERY.get(name, [f'"{name}"']))
        try:
            items = parse(get_text(FEED.format(q=quote(q), days=days), headers=BROWSER_HEADERS, delay=1.0), name)
        except Exception as exc:  # ein Verein nicht erreichbar: die anderen trotzdem
            log(f"  {name}: {exc}")
            continue
        for it in items:
            res = session.execute(text("""
                INSERT INTO news_item (team_id, title, link, source, source_url, kind, published_at, fetched_at)
                VALUES (:t, :title, :link, :source, :source_url, :kind, :published_at, :now)
                ON CONFLICT (team_id, title) DO UPDATE SET kind = EXCLUDED.kind, fetched_at = EXCLUDED.fetched_at
                RETURNING (xmax = 0)"""), {"t": team_id, "now": now, **it})
            n += bool(res.scalar())
        per_team[name] = len(items)
    session.commit()
    return {"neu": n, "je_verein": per_team}


def embed_missing(batch: int = 64) -> int:
    """Embeddings für Überschriften ohne Vektor (LM Studio wie bei den Spielberichten)."""
    import json

    from fussballdb.db.session import engine
    from fussballdb.reports import EMBED_MODEL, embed

    total = 0
    while True:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, title FROM news_item WHERE embedding IS NULL ORDER BY published_at DESC LIMIT :n"),
                                {"n": batch}).all()
        if not rows:
            return total
        vectors = embed([r.title for r in rows])
        with engine.begin() as conn:
            for r, v in zip(rows, vectors):
                conn.execute(text("UPDATE news_item SET embedding = CAST(:v AS vector), embed_model = :m WHERE id = :id"),
                             {"v": json.dumps(v), "m": EMBED_MODEL, "id": r.id})
        total += len(rows)


def search(query: str = "", team_id: int | None = None, days: int = 7, local_only: bool = False,
           limit: int = 20) -> list[dict]:
    """Meldungen zur Frage (Volltext und Bedeutung, Ränge per Reciprocal Rank Fusion wie bei den Spielberichten);
    ohne Frage die neuesten. Filter: Verein, letzte `days` Tage, nur Lokalzeitungen und Verein."""
    import json

    import httpx

    from fussballdb.db.session import engine
    from fussballdb.reports import QUERY_PREFIX, RRF_K, embed

    where = ["n.published_at > now() - make_interval(days => :d)"]
    params: dict = {"d": days, "n": max(limit * 4, 40)}
    if team_id:
        where.append("n.team_id = :t")
        params["t"] = team_id
    if local_only:
        where.append("n.kind IS NOT NULL")
    cond = " AND ".join(where)
    with engine.connect() as conn:
        if not query.strip():
            ids = [r[0] for r in conn.execute(text(f"SELECT id FROM news_item n WHERE {cond} ORDER BY published_at DESC LIMIT :n"), params)]
            ranks = {i: -k for k, i in enumerate(ids)}
        else:
            ranks = {}
            fts = conn.execute(text(f"""SELECT id FROM news_item n WHERE {cond} AND n.tsv @@ websearch_to_tsquery('german', :q)
                                        ORDER BY ts_rank(n.tsv, websearch_to_tsquery('german', :q)) DESC LIMIT :n"""),
                               {**params, "q": query}).all()
            for k, (i,) in enumerate(fts):
                ranks[i] = ranks.get(i, 0) + 1 / (RRF_K + k)
            try:
                vec = json.dumps(embed([query], QUERY_PREFIX)[0])
                for k, (i,) in enumerate(conn.execute(text(f"""SELECT id FROM news_item n WHERE {cond} AND n.embedding IS NOT NULL
                                                             ORDER BY n.embedding <=> CAST(:v AS vector) LIMIT :n"""),
                                                        {**params, "v": vec})):
                    ranks[i] = ranks.get(i, 0) + 1 / (RRF_K + k)
            except (httpx.HTTPError, IndexError, KeyError):
                pass  # ohne LM Studio nur Volltext
        top = sorted(ranks, key=lambda i: -ranks[i])[:limit]
        rows = {r.id: r for r in conn.execute(text("""
            SELECT n.id, n.title, n.link, n.source, n.kind, n.published_at, t.name AS team
            FROM news_item n JOIN team t ON t.id = n.team_id WHERE n.id = ANY(:ids)"""), {"ids": top})}
    return [{"titel": rows[i].title, "quelle": rows[i].source, "art": rows[i].kind, "datum": rows[i].published_at.isoformat(),
             "verein": rows[i].team, "link": rows[i].link} for i in top]


def for_team(team_id: int, before=None, days: int = 7, limit: int = 6) -> list[dict]:
    """Für die Detailseite: die neuesten Meldungen eines Vereins vor `before` (Anpfiff, sonst jetzt), Lokalzeitungen
    und Verein zuerst."""
    from fussballdb.db.session import engine

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT title, link, source, kind, published_at FROM news_item
            WHERE team_id = :t AND published_at <= coalesce(:b, now())
              AND published_at > coalesce(:b, now()) - make_interval(days => :d)
            ORDER BY (kind IS NULL), published_at DESC LIMIT :n"""), {"t": team_id, "b": before, "d": days, "n": limit}).all()
    return [{"titel": r.title, "quelle": r.source, "art": r.kind, "datum": r.published_at.isoformat(), "link": r.link}
            for r in rows]
