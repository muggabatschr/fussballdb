"""Wetter am Stadion zur Spielzeit von Open-Meteo (frei, ohne Schlüssel), für Spiele mit Spielort
(match_venue). Gezählt wird die Stunde nach dem Anpfiff, also die Mitte des Spiels.

Vor dem Spiel ist es die Vorhersage (bis 16 Tage im Voraus, mit Regenwahrscheinlichkeit), danach der
gemessene Wert (Analyse von Open-Meteo); der wird drei Stunden nach dem Anpfiff eingefroren. Die
Vorhersage-Schnittstelle hält Vergangenheitswerte nur etwa 60 Tage vor; fehlt dort ein Wert, kommt er aus
dem Archiv (ERA5, etwa 5 Tage Verzug)."""

import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.models import MatchWeather
from fussballdb.ingest.upsert import upsert

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = "temperature_2m,precipitation,precipitation_probability,weather_code,wind_speed_10m"
HORIZON = timedelta(days=16)  # so weit reicht die Vorhersage
FREEZE_AFTER = timedelta(hours=3)

_client = httpx.Client(headers={"User-Agent": "fussballdb/1.0 (https://github.com/muggabatschr/fussballdb)"}, timeout=30)


def _todo(session: Session) -> list[tuple]:
    """(Wettbewerb, Spiel-ID, Anstoß, lat, lon) für Spiele mit Spielort, deren Wetter noch nicht eingefroren ist
    und für die es schon eine Vorhersage gibt."""
    return session.execute(text("""
        SELECT v.competition, v.match_id, coalesce(m.kickoff, e.kickoff) AS kickoff, v.lat, v.lon
        FROM match_venue v
        LEFT JOIN match m ON v.competition = 'BL' AND m.id = v.match_id
        LEFT JOIN eu_match e ON v.competition <> 'BL' AND e.id = v.match_id
        WHERE v.lat IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM match_weather w WHERE w.competition = v.competition
                          AND w.match_id = v.match_id AND w.kind = 'gemessen')
          AND coalesce(m.kickoff, e.kickoff) <= now() + :h"""), {"h": HORIZON}).all()


def _hourly(lat: float, lon: float, day, archive: bool) -> dict:
    params = {"latitude": round(lat, 3), "longitude": round(lon, 3), "start_date": day.isoformat(),
              "end_date": day.isoformat(), "timezone": "UTC",
              "hourly": HOURLY.replace(",precipitation_probability", "") if archive else HOURLY}
    resp = _client.get(ARCHIVE if archive else FORECAST, params=params)
    resp.raise_for_status()
    return resp.json().get("hourly", {})


def ingest(session: Session, log=print) -> dict:
    """Vorhersage für kommende Spiele (bis 16 Tage), gemessenes Wetter für gespielte."""
    now = datetime.now(timezone.utc)
    cache: dict[tuple, dict] = {}
    rows = []
    for comp, match_id, kickoff, lat, lon in _todo(session):
        hour = (kickoff + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        stamp = hour.strftime("%Y-%m-%dT%H:00")
        measured = kickoff + FREEZE_AFTER < now
        h, i = {}, None
        for archive in ((False, True) if measured else (False,)):
            key = (round(lat, 3), round(lon, 3), hour.date(), archive)
            if key not in cache:
                cache[key] = _hourly(lat, lon, hour.date(), archive)
                time.sleep(0.2)
            h = cache[key]
            i = h["time"].index(stamp) if stamp in h.get("time", []) else None
            if i is not None and h.get("temperature_2m", [None])[i] is not None:
                break
        if i is None or h.get("temperature_2m", [None])[i] is None:
            continue  # noch keine Daten (Archiv hinkt einige Tage hinterher)
        get = lambda k: (h.get(k) or [None] * (i + 1))[i]  # noqa: E731
        rows.append({"competition": comp, "match_id": match_id, "kind": "gemessen" if measured else "vorhersage",
                     "temp_c": get("temperature_2m"), "precip_mm": get("precipitation"),
                     "precip_prob": None if measured else get("precipitation_probability"),
                     "wind_kmh": get("wind_speed_10m"), "weather_code": get("weather_code"), "fetched_at": now})
    upsert(session, MatchWeather, rows, ["competition", "match_id"])
    return {"spiele": len(rows), "abrufe": len(cache)}
