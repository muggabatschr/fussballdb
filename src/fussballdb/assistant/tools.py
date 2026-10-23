"""Werkzeuge, mit denen das Sprachmodell im Chat auf Datenbank und Modell zugreift (Retrieval-Schicht)."""

import json
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine, session_scope
from fussballdb.ingest.team_mapping import TeamResolver
from fussballdb.model.ensemble import MODEL_VERSION

SCHEMA_HINT = """
Tabellen (PostgreSQL):
- season(id, start_year, label)       -- ab 1993; vor 2014 nur Ergebnisse, Statistik (Schüsse ab 2000), Quoten
- team(id, name)                      -- kanonischer Name laut OpenLigaDB
- team_alias(team_id, source, alias)
- match(id, season_id, matchday, kickoff, home_team_id, away_team_id, home_goals, away_goals,
        ht_home_goals, ht_away_goals, finished, openligadb_id, understat_id)
- match_team_stats(match_id, team_id, is_home, goals, xg, npxg, xpts, ppda, deep, big_chances,
        xg_fd, shots, shots_on_target, corners, fouls, yellow_cards, red_cards, possession)
        -- possession ist leer (keine freie Quelle); big_chances = Schüsse mit xG >= 0.3
- shot(id, match_id, team_id, player, player_assisted, minute, xg, result, situation, shot_type, last_action, x, y)
- odds(match_id, bookmaker, is_closing, home, draw, away, over25, under25)   -- bookmaker: B365, PS, BFE, Avg, Max
- elo_rating(match_id, team_id, played_at, elo_before, elo_after)
- prediction(match_id, model_version, created_at, p_home, p_draw, p_away, exp_home_goals, exp_away_goals, p_over25, p_btts)
- player(id, name)
- player_match(match_id, player_id, team_id, position, started, minutes, goals, assists, shots,
        key_passes, xg, xa, xg_chain, xg_buildup, yellow_cards, red_cards)
- player_absence(team_id, player_id, player_name, kind, reason, expected_return, market_value, source, fetched_at, active)
  source: transfermarkt | kickbase (verletzt/Aufbautraining nur laut Kickbase) | karten (Sperren)
"""

TOOLS = [
    {
        "name": "get_upcoming_matches",
        "description": "Die nächsten Bundesliga-Spiele mit gespeicherter Modellprognose (1/X/2, erwartete Tore).",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "Anzahl, Standard 9"}},
                         "additionalProperties": False},
    },
    {
        "name": "get_team_form",
        "description": "Letzte Spiele eines Teams mit Ergebnis, xG, Schüssen, Großchancen, PPDA sowie Durchschnittswerte. "
                       "Achtung: die letzten N Spiele können in die Vorsaison reichen (Feld saison).",
        "input_schema": {"type": "object", "properties": {
            "team": {"type": "string", "description": "Teamname, auch umgangssprachlich (z. B. BVB, Gladbach)"},
            "last_n": {"type": "integer", "description": "Anzahl Spiele, Standard 8"}},
            "required": ["team"], "additionalProperties": False},
    },
    {
        "name": "get_head_to_head",
        "description": "Direkte Bundesliga-Duelle zweier Teams seit 1993/94 mit Ergebnis, xG ab 2014/15.",
        "input_schema": {"type": "object", "properties": {"team_a": {"type": "string"}, "team_b": {"type": "string"}},
                         "required": ["team_a", "team_b"], "additionalProperties": False},
    },
    {
        "name": "predict_match",
        "description": "Modellprognose (Dixon-Coles auf xG mit Formkomponente + Elo, Kaderwert als Startstärke, "
                       "korrigiert um die aktuelle Verletztenliste) für eine Paarung: "
                       "Wahrscheinlichkeiten Heimsieg/Remis/Auswärtssieg, erwartete Tore, wahrscheinlichste Ergebnisse, "
                       "Über 2,5 Tore, beide treffen, Ausfälle mit ihrem Einfluss, Marktquoten falls vorhanden und die "
                       "wahrscheinlichsten Torschützen je Team (p = Chance auf mindestens ein Tor).",
        "input_schema": {"type": "object", "properties": {"home": {"type": "string"}, "away": {"type": "string"}},
                         "required": ["home", "away"], "additionalProperties": False},
    },
    {
        "name": "get_absences",
        "description": "Aktuelle Ausfälle (Verletzungen von Transfermarkt, Sperren aus Karten) eines Teams mit Bedeutung des Spielers.",
        "input_schema": {"type": "object", "properties": {"team": {"type": "string"}},
                         "required": ["team"], "additionalProperties": False},
    },
    {
        "name": "get_table",
        "description": "Tabelle einer Saison mit Punkten, Toren, xG, xGA, xPts, Modell-Punkten (laut Prognosen vor "
                       "den gespielten Spielen erwartet), modell_platz und platz_diff (> 0 = steht besser als erwartet). Solange Spiele offen sind, "
                       "dazu die Hochrechnung zum Saisonende aus den Modell-Wahrscheinlichkeiten (10.000 Simulationen): "
                       "prognose_platz, erw_punkte und p_meister, p_top4, p_abstieg in Prozent.",
        "input_schema": {"type": "object", "properties": {"season": {"type": "integer", "description": "Startjahr, z. B. 2026; Standard: aktuelle Saison"}},
                         "additionalProperties": False},
    },
    {
        "name": "run_sql",
        "description": "Beliebige lesende SQL-Abfrage (nur SELECT/WITH, max. 200 Zeilen) für Fragen, die die anderen Werkzeuge nicht abdecken. Schema:\n" + SCHEMA_HINT,
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"], "additionalProperties": False},
    },
]


def _json(obj) -> str:
    def default(o):
        if isinstance(o, (datetime, date, pd.Timestamp)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return str(o)
    return json.dumps(obj, default=default, ensure_ascii=False)


WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _rows(sql: str, **params) -> list[dict]:
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(sql), params)]
    # Sprachmodelle verrechnen sich beim Wochentag, daher mitliefern
    for row in rows:
        if isinstance(row.get("kickoff"), datetime):
            row["wochentag"] = WOCHENTAGE[row["kickoff"].weekday()]
    return rows


class Toolbox:
    def __init__(self):
        with session_scope() as s:
            self.teams = TeamResolver(s)
        self._model = None

    def _team(self, name: str) -> int:
        team_id = self.teams.find(name)
        if team_id is None:
            raise ValueError(f"Team {name!r} nicht gefunden oder nicht eindeutig.")
        return team_id

    def _forecaster(self):
        if self._model is None:
            from fussballdb.model.predict import build_forecaster
            self._model, _ = build_forecaster()
        return self._model

    def call(self, name: str, args: dict) -> str:
        return _json(getattr(self, name)(**args))

    def get_upcoming_matches(self, limit: int = 9):
        return _rows(
            """
            SELECT m.matchday, m.kickoff, ht.name AS home, at.name AS away,
                   round(p.p_home::numeric, 3) AS p_home, round(p.p_draw::numeric, 3) AS p_draw,
                   round(p.p_away::numeric, 3) AS p_away,
                   round(p.exp_home_goals::numeric, 2) AS exp_home_goals, round(p.exp_away_goals::numeric, 2) AS exp_away_goals,
                   p.created_at AS prediction_from
            FROM match m JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            LEFT JOIN prediction p ON p.match_id = m.id
            WHERE NOT m.finished ORDER BY m.kickoff LIMIT :limit
            """, limit=limit)

    def get_team_form(self, team: str, last_n: int = 8):
        team_id = self._team(team)
        games = _rows(
            """
            SELECT m.kickoff::date AS datum, s.label AS saison, m.matchday,
                   CASE WHEN m.home_team_id = :t THEN 'H' ELSE 'A' END AS ort, opp.name AS gegner,
                   own.goals AS tore, o.goals AS gegentore, m.home_goals, m.away_goals,
                   own.xg, o.xg AS xga, own.shots, o.shots AS shots_against,
                   own.shots_on_target, own.big_chances, o.big_chances AS big_chances_against,
                   own.ppda, own.xpts
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN match_team_stats own ON own.match_id = m.id AND own.team_id = :t
            JOIN match_team_stats o ON o.match_id = m.id AND o.team_id <> :t
            JOIN team opp ON opp.id = o.team_id
            WHERE m.finished ORDER BY m.kickoff DESC LIMIT :n
            """, t=team_id, n=last_n)
        df = pd.DataFrame(games)
        summary = {}
        if not df.empty:
            pts = ((df["tore"] > df["gegentore"]) * 3 + (df["tore"] == df["gegentore"])).sum()
            summary = {"spiele": len(df), "punkte": int(pts),
                       **{f"avg_{c}": round(float(df[c].mean()), 2) for c in
                          ("tore", "gegentore", "xg", "xga", "shots", "shots_against", "big_chances", "big_chances_against", "ppda", "xpts")
                          if df[c].notna().any()}}
        return {"team_id": team_id, "zusammenfassung": summary, "spiele": games}

    def get_head_to_head(self, team_a: str, team_b: str):
        a, b = self._team(team_a), self._team(team_b)
        return _rows(
            """
            SELECT m.kickoff::date AS datum, ht.name AS heim, at.name AS gast, m.home_goals, m.away_goals,
                   hs.xg AS xg_heim, as_.xg AS xg_gast
            FROM match m JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
            LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
            WHERE m.finished AND ((m.home_team_id = :a AND m.away_team_id = :b) OR (m.home_team_id = :b AND m.away_team_id = :a))
            ORDER BY m.kickoff DESC
            """, a=a, b=b)

    def predict_match(self, home: str, away: str):
        from fussballdb.model.predict import predict_pair
        h, a = self._team(home), self._team(away)
        match = _rows(
            "SELECT id, kickoff, matchday FROM match WHERE home_team_id = :h AND away_team_id = :a AND NOT finished ORDER BY kickoff LIMIT 1",
            h=h, a=a)
        match_id = match[0]["id"] if match else None
        kickoff = pd.Timestamp(match[0]["kickoff"]) if match else None
        p = predict_pair(h, a, match_id, self._forecaster(), kickoff=kickoff)
        from fussballdb.model.explain import explain
        from fussballdb.model.predict import market_probs

        names = {r["id"]: r["name"] for r in _rows("SELECT id, name FROM team WHERE id IN (:h, :a)", h=h, a=a)}
        scorer_info = {}
        if match_id is not None:
            from fussballdb.features.scorers import scorers
            sc = scorers(matchdays=34).get(match_id, {})
            scorer_info = {"torschuetzen_heim": sc.get(h, []), "torschuetzen_gast": sc.get(a, [])}
        begruendung = explain(p, names[h], names[a], market_probs().get(match_id) if match_id else None)
        market = _rows(
            "SELECT bookmaker, is_closing, home, draw, away FROM odds WHERE match_id = :m AND bookmaker IN ('Avg', 'B365')",
            m=match_id) if match_id else []
        r = lambda x: round(float(x), 3)
        names = {r["id"]: r["name"] for r in _rows("SELECT id, name FROM team WHERE id IN (:h, :a)", h=h, a=a)}
        scorer_info = {}
        if match_id is not None:
            from fussballdb.features.scorers import scorers
            sc = scorers(matchdays=34).get(match_id, {})
            scorer_info = {"torschuetzen_heim": sc.get(h, []), "torschuetzen_gast": sc.get(a, [])}
        return {
            "heim": names.get(h), "gast": names.get(a), **scorer_info,
            "spiel": match[0] if match else "kein angesetztes Spiel gefunden, Prognose als hypothetische Paarung",
            "p_home": r(p["p_home"]), "p_draw": r(p["p_draw"]), "p_away": r(p["p_away"]),
            "exp_goals": [r(p["exp_home_goals"]), r(p["exp_away_goals"])],
            "p_over25": r(p["p_over25"]), "p_btts": r(p["p_btts"]),
            "wahrscheinlichste_ergebnisse": [f"{i}:{j} ({q * 100:.1f} %)".replace(".", ",") for i, j, q in p["top_scores"]],
            "teilmodelle": {"dixon_coles": {k: r(v) for k, v in p["dc"].items()},
                            "elo": {k: r(v) for k, v in p["elo"].items()}},
            "ausfaelle": {side: {"fehlende_stammspieler": v["missing_regulars"],
                                 "fehlender_offensivanteil": r(v["missing_offense_share"]),
                                 "tor_faktor_angriff": r(v["attack_mult"]), "gegentor_faktor": r(v["concede_mult"])}
                          for side, v in p["absences"].items()},
            "marktquoten": market,
            "tipp": f"{p['tip'][0]}:{p['tip'][1]}",
            "begruendung": begruendung,
        }

    def get_absences(self, team: str):
        from fussballdb.features.availability import AvailabilityModel
        team_id = self._team(team)
        rows = _rows(
            """SELECT player_id, player_name, kind, reason, expected_return, market_value, fetched_at
               FROM player_absence WHERE active AND team_id = :t ORDER BY kind, player_name""", t=team_id)
        prof = AvailabilityModel().player_profile(team_id, pd.Timestamp.now(tz="UTC")).set_index("player_id")
        for row in rows:
            if row["player_id"] in prof.index:
                pr = prof.loc[row["player_id"]]
                row.update(minutenanteil_letzte_spiele=round(float(pr["minute_share"]), 2),
                           anteil_xg_xa=round(float(pr["offense_share"]), 3), stammspieler=bool(pr["regular"]))
        return rows

    def get_table(self, season: int | None = None):
        """Tabelle mit xG/xPts, Modell-Punkten und Modell-Platz (was die Prognosen für die gespielten Spiele
        erwarten ließen; platz_diff > 0 = steht besser da) und, solange Spiele offen sind, der Hochrechnung
        zum Saisonende (prognose_platz, erw_punkte, p_meister, p_top4, p_abstieg in %; model/season_sim.py)."""
        from fussballdb.model.season_sim import simulate

        season = season or _rows("SELECT max(start_year) AS y FROM season")[0]["y"]
        rows = self._table_rows(season)
        # Modell-Punkte: in den gespielten Spielen erwartete Punkte laut Prognose vor dem Spiel
        # (3 × Siegchance + Remischance); Modell-Platz = Platz nach diesen Punkten
        expected = {r["name"]: float(r["modell_pkt"]) for r in _rows(
            """
            SELECT t.name, sum(CASE WHEN t.id = m.home_team_id THEN 3 * p.p_home + p.p_draw
                                    ELSE 3 * p.p_away + p.p_draw END) AS modell_pkt
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
            JOIN team t ON t.id IN (m.home_team_id, m.away_team_id)
            WHERE m.finished AND s.start_year = :y GROUP BY t.name
            """, y=season, v=MODEL_VERSION)}
        if expected:
            order = sorted(rows, key=lambda r: -expected.get(r["name"], 0.0))
            model_rank = {r["name"]: i for i, r in enumerate(order, 1)}
            for i, r in enumerate(rows, 1):
                if r["name"] in expected:
                    r["modell_pkt"] = round(expected[r["name"]], 1)
                    r["modell_platz"] = model_rank[r["name"]]
                    r["platz_diff"] = model_rank[r["name"]] - i  # > 0: steht besser als laut Prognosen erwartet
        sim = simulate(season)
        if not sim.empty:
            by_name = sim.set_index("name")
            for r in rows:
                if r["name"] in by_name.index:
                    s = by_name.loc[r["name"]]
                    r.update({k: float(s[k]) for k in ("erw_punkte", "p_meister", "p_top4", "p_abstieg")})
                    r["prognose_platz"] = int(s["prognose_platz"])
        return rows

    def _table_rows(self, season: int):
        return _rows(
            """
            SELECT t.name, count(*) AS sp,
                   -- bis 1994/95 gab es zwei Punkte für einen Sieg
                   sum(CASE WHEN own.goals > o.goals THEN CASE WHEN s.start_year < 1995 THEN 2 ELSE 3 END
                            WHEN own.goals = o.goals THEN 1 ELSE 0 END) AS pkt,
                   sum(own.goals) AS tore, sum(o.goals) AS gegentore,
                   round(sum(own.xg)::numeric, 1) AS xg, round(sum(o.xg)::numeric, 1) AS xga,
                   round(sum(own.xpts)::numeric, 1) AS xpts
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN match_team_stats own ON own.match_id = m.id
            JOIN match_team_stats o ON o.match_id = m.id AND o.team_id <> own.team_id
            JOIN team t ON t.id = own.team_id
            WHERE m.finished AND s.start_year = :y
            GROUP BY t.name ORDER BY pkt DESC, sum(own.goals) - sum(o.goals) DESC, sum(own.goals) DESC
            """, y=season)

    def run_sql(self, query: str):
        q = query.strip().rstrip(";")
        if not q.lower().startswith(("select", "with")) or ";" in q:
            raise ValueError("Nur eine einzelne SELECT/WITH-Abfrage erlaubt.")
        from sqlalchemy.exc import DBAPIError

        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '10s'"))
            try:
                result = conn.execute(text(q))
            except DBAPIError as exc:
                # als lesbare Meldung zurück, damit das Sprachmodell die Abfrage korrigieren kann (z. B. falsche Spalte)
                msg = str(getattr(exc, "orig", exc)).strip().splitlines()[0]
                raise ValueError(f"SQL-Fehler: {msg}. Tabellen und Spalten stehen in der Werkzeugbeschreibung.") from None
            rows = [dict(r._mapping) for r in result.fetchmany(200)]
            conn.rollback()
        return rows
