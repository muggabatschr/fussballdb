"""Vereinswappen für die Web-App: einheitlich von Transfermarkt, ersatzweise von OpenLigaDB.
Ablage in web/public/logos/<team_id>.<ext> plus web/src/lib/teams.json
(Teamname -> {logo, short}); `short` ist der Kurzname für enge Stellen (Spielkarten)."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from fussballdb.config import DEFAULT_SEASONS, ROOT
from fussballdb.db.models import Team
from fussballdb.ingest.absences import BROWSER_HEADERS
from fussballdb.ingest.http import _client, get_json
from fussballdb.ingest.injury_history import club_ids
from fussballdb.ingest.team_mapping import COLLOQUIAL, TeamResolver

LOGO_DIR = ROOT / "web" / "public" / "logos"
MAPPING = ROOT / "web" / "src" / "lib" / "teams.json"
TM_URL = "https://tmssl.akamaized.net/images/wappen/head/{id}.png"
SIGNATURES = {b"\x89PNG": ".png", b"<svg": ".svg", b"<?xm": ".svg", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}


def _image_ext(data: bytes) -> str | None:
    """Nur echte Bilder speichern (Dateisignatur prüfen)."""
    head = data[:200].lstrip()
    for sig, ext in SIGNATURES.items():
        if head.startswith(sig):
            return ext
    return None


def _openligadb_icons() -> dict[str, str]:
    icons = {}
    for year in DEFAULT_SEASONS:
        for t in get_json(f"https://api.openligadb.de/getavailableteams/bl1/{year}"):
            if t.get("teamIconUrl"):
                icons[t["teamName"]] = t["teamIconUrl"]
    return icons


def ingest(session: Session, force: bool = False) -> dict:
    teams = list(session.scalars(select(Team)))
    clubs = club_ids(TeamResolver(session))
    fallback = _openligadb_icons()
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    mapping, sources, missing = {}, {"transfermarkt": 0, "openligadb": 0, "vorhanden": 0}, []
    for team in teams:
        existing = sorted(LOGO_DIR.glob(f"{team.id}.*"))
        if existing and not force:
            mapping[team.name] = f"/logos/{existing[0].name}"
            sources["vorhanden"] += 1
            continue
        candidates = []
        if team.id in clubs:
            candidates.append(("transfermarkt", TM_URL.format(id=clubs[team.id][1])))
        if team.name in fallback:
            candidates.append(("openligadb", fallback[team.name]))
        for source, url in candidates:
            try:
                resp = _client.get(url, headers=BROWSER_HEADERS)
                resp.raise_for_status()
            except Exception:
                continue
            ext = _image_ext(resp.content)
            if ext:
                path = LOGO_DIR / f"{team.id}{ext}"
                path.write_bytes(resp.content)
                mapping[team.name] = f"/logos/{path.name}"
                sources[source] += 1
                break
        else:
            missing.append(team.name)
    write_team_info(teams, mapping)
    return {"quellen": sources, "fehlen": missing}


def write_team_info(teams: list[Team], logos: dict[str, str]) -> None:
    """Kurzname = erster umgangssprachlicher Name aus team_mapping (z. B. "Gladbach")."""
    info = {t.name: {"logo": logos.get(t.name), "short": (COLLOQUIAL.get(t.name) or [t.name])[0]} for t in teams}
    MAPPING.write_text(json.dumps(dict(sorted(info.items())), ensure_ascii=False, indent=2) + "\n")
