"""Europapokal-Belastung: Ein Bundesliga-Team, das in den 4 Tagen vor dem Spiel ein Europapokalspiel hatte
(Champions League, Europa League laut eu_match), bekommt 10 % weniger Torerwartung.

Rückblick-Test 2024–2026 (fussballdb belastung-test): in allen 3 Saisons besser, in über 99 % der
Bootstrap-Ziehungen. Kontrolle: Dieselben Teams in Spielen ohne Europapokal davor abzuwerten schadet,
es ist also die Belastung (Rotation, Müdigkeit) und keine generelle Überschätzung großer Teams. Größere
Abschläge waren im Test noch besser; 10 % ist bei 103 betroffenen Spielen bewusst vorsichtig.
"""

import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

EURO_LOAD = 0.10
EURO_LOAD_DAYS = 4
COMPETITION_NAMES = {"CL": "der Champions League", "EL": "der Europa League"}


def euro_schedule() -> dict[int, list[tuple[pd.Timestamp, str]]]:
    """Europapokalspiele (auch künftige) je Bundesliga-Team, Zuordnung über den Vereinsnamen."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT t.id, m.kickoff, m.competition FROM eu_match m
            JOIN eu_team et ON et.id IN (m.home_id, m.away_id) JOIN team t ON t.name = et.name
            WHERE m.competition IN ('CL', 'EL')""")).all()
    out: dict[int, list[tuple[pd.Timestamp, str]]] = {}
    for team, kickoff, comp in rows:
        out.setdefault(team, []).append((pd.Timestamp(kickoff), comp))
    return out


def apply(impact: dict, team_id: int, kickoff: pd.Timestamp, schedule: dict, factor: float = EURO_LOAD,
          days: int = EURO_LOAD_DAYS) -> dict:
    """Ausfall-Wirkung (AvailabilityModel.impact) um die Belastung ergänzen: attack_mult × (1 − factor),
    dazu euro_load = {tage, wettbewerb} für die Begründung."""
    kickoff = pd.Timestamp(kickoff)
    recent = [(kickoff - k, comp) for k, comp in schedule.get(team_id, [])
              if pd.Timedelta(0) < kickoff - k <= pd.Timedelta(days=days)]
    if not recent or factor <= 0:
        return impact
    gap, comp = min(recent)
    out = dict(impact)
    out["attack_mult"] = out.get("attack_mult", 1.0) * (1 - factor)
    out["euro_load"] = {"tage": max(1, round(gap / pd.Timedelta(days=1))), "wettbewerb": comp, "faktor": 1 - factor}
    return out
