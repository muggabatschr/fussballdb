"""Prüft, ob Daten fehlen oder veraltet sind, und führt nur die nötigen Update-Schritte aus.

Aufruf über `fussballdb ensure`, beim Start der API (im Hintergrund) und täglich per launchd.
Jeder Schritt wird in update_log protokolliert. Ein Schritt läuft frühestens nach `min_interval`
erneut, auch wenn er noch nötig wäre (z. B. Understat hat ein xG noch nicht veröffentlicht).
Eine Postgres-Sperre verhindert, dass zwei Updates gleichzeitig laufen (API und launchd)."""

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from fussballdb.config import DEFAULT_SEASONS
from fussballdb.db.session import engine, session_scope

LOCK_ID = 4242_2026
CURRENT_SEASON = max(DEFAULT_SEASONS)

# Zustand für die API (/status)
STATUS: dict = {"running": False, "step": None, "started_at": None, "finished_at": None, "results": []}
_thread_lock = threading.Lock()


def _scalar(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


# --- Prüfungen: liefern einen Grund (Text), wenn der Schritt nötig ist, sonst None ---------------

def _need_results() -> str | None:
    n = _scalar(
        """
        SELECT count(*) FROM match m JOIN season s ON s.id = m.season_id
        WHERE s.start_year = :y AND (
            (NOT m.finished AND m.kickoff < now() - interval '2 hours 30 minutes')
            OR (m.finished AND m.kickoff > now() - interval '14 days'
                AND NOT EXISTS (SELECT 1 FROM match_team_stats x WHERE x.match_id = m.id AND x.xg IS NOT NULL))
            OR (m.finished AND m.kickoff BETWEEN now() - interval '30 days' AND now() - interval '3 days'
                AND NOT EXISTS (SELECT 1 FROM match_team_stats x WHERE x.match_id = m.id AND x.shots IS NOT NULL)))
        """,
        y=CURRENT_SEASON,
    )
    if _scalar("SELECT count(*) FROM match") == 0:
        return "Datenbank ist leer"
    return f"{n} gespielte Spiele ohne Ergebnis, xG oder Statistik" if n else None


def _need_odds() -> str | None:
    n = _scalar(
        """
        SELECT count(*) FROM match m
        WHERE NOT m.finished AND m.kickoff BETWEEN now() AND now() + interval '7 days'
          AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.match_id = m.id)
        """
    )
    return f"{n} Spiele der nächsten 7 Tage ohne Quoten" if n else None


WOCHENTAGE = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]


def _tag(d: date) -> str:
    return f"{WOCHENTAGE[d.weekday()]} {d:%d.%m.}"


def _odds_hint() -> str | None:
    """Erklärt fehlende Vorab-Quoten: football-data stellt einen Spieltag meist erst 1–2 Tage vor dem
    ersten Anpfiff in fixtures.csv ein. Bis dahin ist das kein Fehler."""
    first = _scalar(
        """
        SELECT min(m.kickoff) FROM match m
        WHERE NOT m.finished AND m.kickoff BETWEEN now() AND now() + interval '7 days'
          AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.match_id = m.id)
        """
    )
    if first is None:
        return None
    day = first.date()
    early, late = day - timedelta(days=2), day - timedelta(days=1)
    if date.today() < early:
        return (f"Kein Fehler: football-data.co.uk hat die Quoten noch nicht bereitgestellt. Sie kommen meist "
                f"1–2 Tage vor dem ersten Anpfiff ({_tag(day)}), voraussichtlich am {_tag(early)} oder {_tag(late)} "
                f"Das tägliche Update holt sie dann automatisch.")
    return (f"Kein Fehler: football-data.co.uk hat die Quoten noch nicht bereitgestellt, obwohl sie meist ab "
            f"{_tag(early)} da sind. Das Update versucht es alle 6 Stunden erneut, spätestens vor dem "
            f"ersten Anpfiff ({_tag(day)}) sollten sie kommen.")


def _need_snapshot() -> str | None:
    last = _scalar("SELECT max(fetched_at) FROM lineup_snapshot")
    if last is None or last < datetime.now(timezone.utc) - timedelta(hours=20):
        return "Verletzte und Aufstellungen älter als 20 Stunden" if last else "noch kein Schnappschuss"
    return None


def _need_squad_values() -> str | None:
    first = date.today().replace(day=1)
    n = _scalar("SELECT count(*) FROM squad_value WHERE stichtag = :d", d=first)
    return None if n else f"Kaderwerte zum {first:%d.%m.%Y} fehlen"


def _need_injury_history() -> str | None:
    if not _scalar("SELECT count(*) FROM player_injury"):
        return "Verletzungshistorie fehlt"
    if not _scalar("SELECT count(*) FROM update_log WHERE step = 'verletzungshistorie' AND ok"):
        return "Verletzungshistorie noch nicht vollständig geladen"
    return None


def _need_kickbase_daily() -> str | None:
    from fussballdb.ingest.kickbase import TOKEN_FILE

    if not TOKEN_FILE.exists():
        return None  # kein Kickbase-Zugang hinterlegt
    last = _scalar("SELECT max(fetched_at) FROM kb_league_entry")
    if last is None or last < datetime.now(timezone.utc) - timedelta(hours=20):
        return "Kickbase-Marktwerte älter als 20 Stunden"
    return None


def _need_kickbase_points() -> str | None:
    from fussballdb.ingest.kickbase import TOKEN_FILE

    if not TOKEN_FILE.exists():
        return None
    last_match = _scalar("SELECT max(kickoff) FROM match WHERE finished")
    last_points = _scalar("SELECT max(kickoff) FROM kb_points")
    if last_points is None:
        return "Kickbase-Punkte fehlen"
    if last_match and last_match > last_points + timedelta(hours=3):
        return "neuer Spieltag ohne Kickbase-Punkte"
    if _scalar("SELECT count(*) FROM kb_player WHERE updated_at < now() - interval '8 days'"):
        return "Kickbase-Spieler nicht vollständig geladen"
    return None


def _run_kickbase_daily() -> str:
    from fussballdb.ingest import kickbase

    with session_scope() as s:
        r = kickbase.ingest_daily(s)
    return f"{r['aktualisiert']} Marktwerte, Markt {r['markt']}, Kader {r['kader']}" + (f", {r['neu']} neue Spieler" if r["neu"] else "")


def _run_kickbase_points() -> str:
    from fussballdb.ingest import kickbase

    with session_scope() as s:
        r = kickbase.ingest_players(s)
    return f"{r['spieler']} Spieler, {r['punkte']} Punkte-Einträge"


def _need_backfill() -> str | None:
    n = _scalar(
        """
        SELECT count(*) FROM match m
        WHERE m.finished AND m.kickoff > (SELECT min(kickoff) FROM match) + interval '10 days'
          AND NOT EXISTS (SELECT 1 FROM prediction p WHERE p.match_id = m.id)
        """
    )
    return f"{n} gespielte Spiele ohne Prognose" if n else None


def _need_predictions() -> str | None:
    missing = _scalar(
        """
        SELECT count(*) FROM match m JOIN season s ON s.id = m.season_id
        WHERE s.start_year = :y AND NOT m.finished
          AND NOT EXISTS (SELECT 1 FROM prediction p WHERE p.match_id = m.id AND p.basis = 'live')
        """,
        y=CURRENT_SEASON,
    )
    if missing:
        return f"{missing} offene Spiele ohne Prognose"
    last_pred = _scalar("SELECT max(as_of) FROM prediction WHERE basis = 'live'")
    last_data = _scalar(
        "SELECT max(finished_at) FROM update_log WHERE ok AND step IN ('ergebnisse', 'ausfaelle', 'kaderwerte')"
    )
    if last_pred and last_data and last_data > last_pred:
        return "neue Daten seit der letzten Prognose"
    if last_pred and last_pred < datetime.now(timezone.utc) - timedelta(hours=24):
        return "Prognosen älter als 24 Stunden"
    return None


def _need_europe() -> str | None:
    """Champions League: Ergebnisse, Ligaspiele, Kaderwerte und Prognosen."""
    if not _scalar("SELECT count(*) FROM eu_match WHERE competition = 'CL'"):
        return None  # Europa noch nie geladen (fussballdb europa), nicht automatisch nachholen
    open_ = _scalar("SELECT count(*) FROM eu_match WHERE NOT finished AND kickoff < now() - interval '3 hours'")
    if open_:
        return f"{open_} Europapokal-Spiele ohne Ergebnis"
    last_league = _scalar("SELECT max(kickoff) FROM eu_match WHERE competition NOT IN ('CL', 'EL')")
    if last_league and last_league < datetime.now(timezone.utc) - timedelta(days=4):
        return "Ligaspiele für die Europa-Elo älter als 4 Tage"
    missing = _scalar(
        """SELECT count(*) FROM eu_match m WHERE m.competition = 'CL' AND NOT m.finished AND m.kickoff > now()
           AND NOT EXISTS (SELECT 1 FROM eu_prediction p WHERE p.match_id = m.id AND p.basis = 'live')"""
    )
    if missing:
        return f"{missing} offene CL-Spiele ohne Prognose"
    last_pred = _scalar("SELECT max(as_of) FROM eu_prediction WHERE basis = 'live'")
    if last_pred and last_pred < datetime.now(timezone.utc) - timedelta(hours=24):
        return "CL-Prognosen älter als 24 Stunden"
    return None


def _need_tv() -> str | None:
    """TV-Sender: täglich neu laden, solange Spiele in den nächsten 7 Tagen anstehen."""
    upcoming = _scalar("""SELECT (SELECT count(*) FROM match WHERE NOT finished AND kickoff BETWEEN now() AND now() + interval '7 days')
                         + (SELECT count(*) FROM eu_match WHERE competition = 'CL' AND NOT finished
                            AND kickoff BETWEEN now() AND now() + interval '7 days')""")
    if not upcoming:
        return None
    last = _scalar("SELECT max(fetched_at) FROM tv_listing")
    if last is None or last < datetime.now(timezone.utc) - timedelta(hours=20):
        return "TV-Sender älter als 20 Stunden" if last else "noch keine TV-Sender"
    return None


# --- Ausführung -------------------------------------------------------------------------------------

def _run_results() -> str:
    from fussballdb.ingest import football_data, openligadb, understat

    with session_scope() as s:
        n_ol = openligadb.ingest_season(s, CURRENT_SEASON)
    with session_scope() as s:
        n_fd, _ = football_data.ingest_season(s, CURRENT_SEASON)
    with session_scope() as s:
        n_us, _ = understat.ingest_season(s, CURRENT_SEASON)
    return f"OpenLigaDB {n_ol}, football-data {n_fd}, Understat {n_us} Spiele"


def _run_odds() -> str:
    from fussballdb.ingest import football_data

    with session_scope() as s:
        n, listed = football_data.ingest_fixture_odds(s)
    message = f"Quoten für {n} Spiele"
    if not listed:
        hint = _odds_hint()
        if hint:
            message += f". {hint}"
    elif listed > n:
        message += f". [Warnung] {listed - n} Bundesliga-Spiele in fixtures.csv ließen sich nicht zuordnen"
    return message


def _run_snapshot() -> str:
    from fussballdb.ingest import absences, lineups

    with session_scope() as s:
        a = absences.ingest(s)
    with session_scope() as s:
        l = lineups.ingest(s)
    return f"{a['injuries']} Verletzte, {a['suspensions']} Sperren, Aufstellungen von {l['teams']} Teams"


def _run_squad_values() -> str:
    from fussballdb.ingest import squad_values

    with session_scope() as s:
        n, _ = squad_values.ingest(s, date.today().replace(day=1))
    return f"{n} Kaderwerte"


def _run_injury_history() -> str:
    from fussballdb.ingest import injury_history

    with session_scope() as s:
        n, failed = injury_history.ingest(s)
    return f"{n} Verletzungen" + (f", {len(failed)} Seiten übersprungen" if failed else "")


def _run_backfill() -> str:
    from fussballdb.model.predict import backfill

    return f"{backfill()} Rückblick-Prognosen"


def _run_predictions() -> str:
    from fussballdb.model.predict import predict_upcoming

    return f"{len(predict_upcoming())} Live-Prognosen"


def _run_europe() -> str:
    from fussballdb.ingest import europe
    from fussballdb.model.europe import backfill as eu_backfill, predict_upcoming as eu_predict

    with session_scope() as s:
        n_eu = europe.ingest_euro(s)
    with session_scope() as s:
        n_league = europe.ingest_domestic(s, [CURRENT_SEASON])
    n_values = 0
    last_value = _scalar("SELECT max(stichtag) FROM eu_squad_value")
    if last_value is None or last_value < date.today() - timedelta(days=30):
        with session_scope() as s:
            n_values, _ = europe.ingest_values(s, start=(last_value or date(europe.FIRST_SEASON, 7, 1)) + timedelta(days=1),
                                               log=lambda m: None)
    return (f"Europapokal {n_eu}, Ligaspiele {n_league}, Kaderwerte {n_values}, "
            f"Rückblick {eu_backfill()}, Live {eu_predict()} CL-Prognosen")


def _run_tv() -> str:
    from fussballdb.ingest import tv

    with session_scope() as s:
        res = tv.ingest(s)
    return f"TV-Sender für {res['zugeordnet']} Spiele/Länder" + (
        f", nicht zugeordnet: {', '.join(res['nicht_zugeordnet'][:5])}" if res["nicht_zugeordnet"] else "")


@dataclass
class Step:
    name: str
    label: str
    needed: Callable[[], str | None]
    run: Callable[[], str]
    min_interval: timedelta
    slow: bool = False
    hint: Callable[[], str | None] | None = None  # erklärt, warum Daten fehlen dürfen (kein Fehler)


STEPS = [
    Step("ergebnisse", "Ergebnisse, xG, Statistiken", _need_results, _run_results, timedelta(hours=3)),
    Step("kaderwerte", "Kaderwerte", _need_squad_values, _run_squad_values, timedelta(hours=24)),
    Step("ausfaelle", "Verletzte und Aufstellungen", _need_snapshot, _run_snapshot, timedelta(hours=2)),
    Step("quoten", "Vorab-Quoten", _need_odds, _run_odds, timedelta(hours=6), hint=_odds_hint),
    Step("rueckblick", "Rückblick-Prognosen", _need_backfill, _run_backfill, timedelta(hours=6)),
    Step("kickbase", "Kickbase-Marktwerte und Liga", _need_kickbase_daily, _run_kickbase_daily, timedelta(hours=6)),
    Step("prognosen", "Live-Prognosen", _need_predictions, _run_predictions, timedelta(hours=1)),
    Step("europa", "Champions League", _need_europe, _run_europe, timedelta(hours=6)),
    Step("tv", "TV-Sender (DE, AT)", _need_tv, _run_tv, timedelta(hours=6)),
    Step("verletzungshistorie", "Verletzungshistorie", _need_injury_history, _run_injury_history,
         timedelta(days=7), slow=True),
    Step("kickbase_punkte", "Kickbase-Punkte und neue Spieler", _need_kickbase_points, _run_kickbase_points,
         timedelta(hours=12), slow=True),
]


def _last_run(step: str) -> datetime | None:
    return _scalar("SELECT max(started_at) FROM update_log WHERE step = :s", s=step)


def check() -> list[dict]:
    """Welche Schritte wären jetzt nötig? (ohne etwas auszuführen)"""
    out = []
    for step in STEPS:
        try:
            reason = step.needed()
        except Exception as exc:  # z. B. Tabelle fehlt noch
            reason = f"Prüfung fehlgeschlagen: {exc}"
        last = _last_run(step.name)
        blocked = bool(reason and last and last > datetime.now(timezone.utc) - step.min_interval)
        hint = step.hint() if reason and step.hint else None
        out.append({"step": step.name, "label": step.label, "reason": reason, "last_run": last,
                    "waiting": blocked, "hint": hint})
    return out


def ensure(force: bool = False, include_slow: bool = True, only: set[str] | None = None,
           log: Callable[[str], None] = print) -> list[dict]:
    """Führt die nötigen Schritte aus. force=True: alle Schritte (außer langsamen) unabhängig vom Zustand."""
    results = []
    with engine.connect() as lock_conn:
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar():
            log("Ein anderes Update läuft bereits, nichts zu tun.")
            return [{"step": "-", "status": "läuft bereits"}]
        try:
            STATUS.update(running=True, started_at=datetime.now(timezone.utc), finished_at=None, results=results)
            for step in STEPS:
                if only and step.name not in only:
                    continue
                if step.slow and not include_slow and not (only and step.name in only):
                    continue
                reason = "erzwungen" if force and not step.slow else step.needed()
                if not reason:
                    results.append({"step": step.name, "status": "aktuell"})
                    continue
                last = _last_run(step.name)
                if not force and last and last > datetime.now(timezone.utc) - step.min_interval:
                    hint = step.hint() if step.hint else None
                    results.append({"step": step.name, "status": "wartet", "reason": reason, "hint": hint})
                    log(f"{step.label}: nötig ({reason}), lief aber zuletzt {last:%d.%m. %H:%M} – später erneut")
                    if hint:
                        log(f"  {hint}")
                    continue
                STATUS["step"] = step.label
                log(f"{step.label}: {reason} …")
                with engine.begin() as conn:
                    log_id = conn.execute(
                        text("INSERT INTO update_log (step, started_at, reason) VALUES (:s, now(), :r) RETURNING id"),
                        {"s": step.name, "r": reason[:300]},
                    ).scalar()
                ok, message = True, ""
                try:
                    message = step.run()
                    log(f"  {message}")
                except Exception as exc:
                    ok, message = False, f"{exc}"
                    log(f"  [Fehler] {exc}")
                    traceback.print_exc()
                with engine.begin() as conn:
                    conn.execute(text("UPDATE update_log SET finished_at = now(), ok = :ok, message = :m WHERE id = :id"),
                                 {"ok": ok, "m": message[:1000], "id": log_id})
                results.append({"step": step.name, "status": "ok" if ok else "fehler", "reason": reason, "message": message})
        finally:
            STATUS.update(running=False, step=None, finished_at=datetime.now(timezone.utc))
            lock_conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    return results


def ensure_in_background(on_done: Callable[[], None] | None = None, **kwargs) -> bool:
    """Startet ensure() in einem Thread (für die API). False, wenn bereits eines läuft."""
    if not _thread_lock.acquire(blocking=False):
        return False

    def worker():
        try:
            ensure(log=lambda m: print(f"[update] {m}", flush=True), **kwargs)
            if on_done:
                on_done()
        finally:
            _thread_lock.release()

    threading.Thread(target=worker, daemon=True, name="fussballdb-ensure").start()
    return True
