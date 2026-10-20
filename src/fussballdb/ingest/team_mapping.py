"""Ordnet die Teamnamen der einzelnen Quellen einem Team zu (kanonisch: OpenLigaDB-Name)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from fussballdb.db.models import Team, TeamAlias

# kanonischer Name -> {quelle: alias}
TEAMS: dict[str, dict[str, str]] = {
    "FC Augsburg": {"football_data": "Augsburg", "understat": "Augsburg"},
    "FC Bayern München": {"football_data": "Bayern Munich", "understat": "Bayern Munich"},
    "VfL Bochum": {"football_data": "Bochum", "understat": "Bochum"},
    "Borussia Dortmund": {"football_data": "Dortmund", "understat": "Borussia Dortmund"},
    "SV Darmstadt 98": {"football_data": "Darmstadt", "understat": "Darmstadt"},
    "Eintracht Frankfurt": {"football_data": "Ein Frankfurt", "understat": "Eintracht Frankfurt"},
    "SV 07 Elversberg": {"football_data": "Elversberg", "understat": "Elversberg"},
    "1. FC Köln": {"football_data": "FC Koln", "understat": "FC Cologne"},
    "SC Freiburg": {"football_data": "Freiburg", "understat": "Freiburg"},
    "Hamburger SV": {"football_data": "Hamburg", "understat": "Hamburger SV"},
    "1. FC Heidenheim 1846": {"football_data": "Heidenheim", "understat": "FC Heidenheim"},
    "TSG Hoffenheim": {"football_data": "Hoffenheim", "understat": "Hoffenheim"},
    "Holstein Kiel": {"football_data": "Holstein Kiel", "understat": "Holstein Kiel"},
    "Bayer 04 Leverkusen": {"football_data": "Leverkusen", "understat": "Bayer Leverkusen"},
    "Borussia Mönchengladbach": {"football_data": "M'gladbach", "understat": "Borussia M.Gladbach"},
    "1. FSV Mainz 05": {"football_data": "Mainz", "understat": "Mainz 05"},
    "SC Paderborn 07": {"football_data": "Paderborn", "understat": "Paderborn"},
    "RB Leipzig": {"football_data": "RB Leipzig", "understat": "RasenBallsport Leipzig"},
    "FC Schalke 04": {"football_data": "Schalke 04", "understat": "Schalke 04"},
    "FC St. Pauli": {"football_data": "St Pauli", "understat": "St. Pauli"},
    "VfB Stuttgart": {"football_data": "Stuttgart", "understat": "VfB Stuttgart"},
    "1. FC Union Berlin": {"football_data": "Union Berlin", "understat": "Union Berlin"},
    "SV Werder Bremen": {"football_data": "Werder Bremen", "understat": "Werder Bremen"},
    "VfL Wolfsburg": {"football_data": "Wolfsburg", "understat": "Wolfsburg"},
    # ab 2014/15 (für ältere Saisons)
    "Hertha BSC": {"football_data": "Hertha", "understat": "Hertha Berlin"},
    "Hannover 96": {"football_data": "Hannover", "understat": "Hannover 96"},
    "FC Ingolstadt 04": {"football_data": "Ingolstadt", "understat": "Ingolstadt"},
    "1. FC Nürnberg": {"football_data": "Nurnberg", "understat": "Nuernberg"},
    "Fortuna Düsseldorf": {"football_data": "Fortuna Dusseldorf", "understat": "Fortuna Duesseldorf"},
    "DSC Arminia Bielefeld": {"football_data": "Bielefeld", "understat": "Arminia Bielefeld"},
    "SpVgg Greuther Fürth": {"football_data": "Greuther Furth", "understat": "Greuther Fuerth"},
}

# Transfermarkt schreibt einige Vereine anders (ohne Eintrag: wie OpenLigaDB)
TRANSFERMARKT: dict[str, list[str]] = {
    "1. FC Köln": ["1.FC Köln"],
    "1. FC Union Berlin": ["1.FC Union Berlin"],
    "1. FSV Mainz 05": ["1.FSV Mainz 05"],
    "TSG Hoffenheim": ["TSG 1899 Hoffenheim"],
    "1. FC Heidenheim 1846": ["1.FC Heidenheim 1846"],
    "1. FC Nürnberg": ["1.FC Nürnberg"],
    "DSC Arminia Bielefeld": ["Arminia Bielefeld"],
}

# Umgangssprachliche Namen, damit Abfragen wie "Bayern gegen Gladbach" funktionieren
COLLOQUIAL: dict[str, list[str]] = {
    "FC Bayern München": ["Bayern", "FCB", "Bayern München"],
    "Borussia Dortmund": ["Dortmund", "BVB"],
    "Bayer 04 Leverkusen": ["Leverkusen", "Bayer"],
    "Borussia Mönchengladbach": ["Gladbach", "Mönchengladbach", "BMG"],
    "Eintracht Frankfurt": ["Frankfurt", "SGE", "Eintracht"],
    "1. FC Köln": ["Köln", "Koeln", "FC Köln"],
    "1. FC Union Berlin": ["Union", "Union Berlin"],
    "1. FSV Mainz 05": ["Mainz", "Mainz 05"],
    "SV Werder Bremen": ["Bremen", "Werder"],
    "VfB Stuttgart": ["Stuttgart", "VfB"],
    "VfL Wolfsburg": ["Wolfsburg"],
    "SC Freiburg": ["Freiburg"],
    "TSG Hoffenheim": ["Hoffenheim", "TSG"],
    "FC Augsburg": ["Augsburg", "FCA"],
    "RB Leipzig": ["Leipzig", "RBL"],
    "Hamburger SV": ["HSV", "Hamburg"],
    "FC St. Pauli": ["St. Pauli", "Pauli"],
    "1. FC Heidenheim 1846": ["Heidenheim"],
    "FC Schalke 04": ["Schalke", "S04"],
    "SC Paderborn 07": ["Paderborn"],
    "SV 07 Elversberg": ["Elversberg"],
    "VfL Bochum": ["Bochum"],
    "SV Darmstadt 98": ["Darmstadt", "Lilien"],
    "Holstein Kiel": ["Kiel"],
    "Hertha BSC": ["Hertha", "Hertha Berlin"],
    "Hannover 96": ["Hannover", "96"],
    "FC Ingolstadt 04": ["Ingolstadt", "FCI"],
    "1. FC Nürnberg": ["Nürnberg", "Club", "FCN"],
    "Fortuna Düsseldorf": ["Düsseldorf", "Fortuna", "F95"],
    "DSC Arminia Bielefeld": ["Bielefeld", "Arminia"],
    "SpVgg Greuther Fürth": ["Fürth", "Greuther Fürth"],
}


def seed_teams(session: Session) -> None:
    """Legt alle bekannten Teams und Aliase an (idempotent)."""
    existing = {t.name: t for t in session.scalars(select(Team))}
    known_aliases = {(a.source, a.alias) for a in session.scalars(select(TeamAlias))}
    for name, sources in TEAMS.items():
        team = existing.get(name)
        if team is None:
            team = Team(name=name)
            session.add(team)
            session.flush()
        entries = [("openligadb", name), *sources.items()]
        entries += [("transfermarkt", alias) for alias in TRANSFERMARKT.get(name, [name])]
        entries += [("colloquial", alias) for alias in COLLOQUIAL.get(name, [])]
        for source, alias in entries:
            if (source, alias) not in known_aliases:
                session.add(TeamAlias(team_id=team.id, source=source, alias=alias))
                known_aliases.add((source, alias))


class TeamResolver:
    """Löst Quellnamen auf Team-IDs auf und meldet unbekannte Namen laut."""

    def __init__(self, session: Session):
        self._by_source: dict[tuple[str, str], int] = {
            (a.source, a.alias): a.team_id for a in session.scalars(select(TeamAlias))
        }
        self._any: dict[str, int] = {
            alias.casefold(): team_id for (_, alias), team_id in self._by_source.items()
        }

    def resolve(self, source: str, name: str) -> int:
        team_id = self._by_source.get((source, name))
        if team_id is None:
            raise KeyError(
                f"Unbekannter Teamname {name!r} aus Quelle {source!r}. "
                "Bitte in fussballdb/ingest/team_mapping.py ergänzen."
            )
        return team_id

    def find(self, name: str) -> int | None:
        """Freie Suche über alle Aliase (für Chat und CLI)."""
        key = name.strip().casefold()
        if key in self._any:
            return self._any[key]
        matches = {tid for alias, tid in self._any.items() if key in alias}
        return matches.pop() if len(matches) == 1 else None
