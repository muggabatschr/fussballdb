"""MCP-Server: macht Datenbank und Prognosemodell für Claude Desktop und Claude Code nutzbar.

Claude ruft diese Werkzeuge auf, es wird kein API-Schlüssel benötigt; abgerechnet wird über das
Claude-Abo. Start über stdio (`uv run fussballdb-mcp`), die Datenbank muss laufen (docker compose)."""

import json

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from fussballdb.assistant.tools import SCHEMA_HINT, Toolbox, _json

INSTRUCTIONS = """Daten und Prognosen zur 1. Fußball-Bundesliga (Ergebnisse seit 1993/94, xG, Prognosen und
Spielerdaten seit 2014/15), zur Champions League (ab 2024/25,
Werkzeug `champions_league`), zur 2. Bundesliga und zum DFB-Pokal (Werkzeug `wettbewerb`) und zu Kickbase: Ergebnisse, xG, Schüsse,
Großchancen, PPDA, Kader, Verletzte, Kaderwerte, Wettquoten sowie ein statistisches Prognosemodell
(Dixon-Coles auf xG mit Formkomponente + Elo, Kaderwert als Startstärke, Verletzte eingerechnet).

- Wahrscheinlichkeiten nur aus `prognose`, `naechste_spiele` oder `spieltag` übernehmen, nie selbst schätzen.
  Einordnen (Form, Ausfälle, Marktquoten) ist erwünscht, die Zahlen nicht verändern.
- Verletzte sind in den Wahrscheinlichkeiten bereits eingerechnet.
- Der Tipp ist das Ergebnis mit den meisten erwarteten Punkten nach der Punkteregel der Tipprunde.
- Prognosen sind Wahrscheinlichkeiten, keine Wettempfehlung. Ballbesitz liegt nicht vor.
- Teamnamen dürfen umgangssprachlich sein (BVB, Gladbach, Bayern).
- Tipps hängen von der Punkteregel der Kicktipp-Tipprunde ab: `tipprunden` listet die Runden, `spieltag` mit
  `tipprunde` liefert Tipps und Punkte nach ihrer Regel; ohne Angabe gilt die Standardrunde.
- Spielverläufe und Zusammenfassungen: Werkzeug `spielberichte` (Bundesliga ab 2014/15).
- Anreise zum Spiel: Werkzeug `anreise` (Google-Maps-Link mit Bus und Bahn, Ankunft eine Stunde vor dem
  Anpfiff); den Ort des Nutzers als `start` mitgeben, wenn er ihn nennt.
- Vor 2014/15 gibt es nur Ergebnisse, Statistik (Schüsse ab 2000/01, Karten, Ecken) und Quoten, kein xG und
  keine Prognosen. 1993/94 und 1994/95 gab es zwei Punkte für einen Sieg (die Tabelle rechnet das so)."""

mcp = MCPServer(name="fussballdb", title="Bundesliga-Prognosen", instructions=INSTRUCTIONS)
_toolbox: Toolbox | None = None
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _tb() -> Toolbox:
    global _toolbox
    if _toolbox is None:  # erst beim ersten Aufruf: Modell trainieren dauert einige Sekunden
        _toolbox = Toolbox()
    return _toolbox


def _call(tool: str, args: dict) -> str:
    """Werkzeug aufrufen; Fehler wie unbekannte Teamnamen gehen als lesbare Meldung an Claude zurück."""
    try:
        return _tb().call(tool, args)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def naechste_spiele(anzahl: int = 9) -> str:
    """Die nächsten Bundesliga-Spiele mit gespeicherter Prognose (Heimsieg/Remis/Auswärtssieg, erwartete Tore)."""
    return _call("get_upcoming_matches", {"limit": anzahl})


@mcp.tool(annotations=READ_ONLY)
def spieltag(saison: int, spieltag: int, tipprunde: str | None = None) -> str:
    """Alle Spiele eines Spieltags mit Ergebnis, xG, Prognose, Tipp des Modells und Tipp-Punkten sowie
    der Bilanz des Spieltags und der Saison. saison = Startjahr (2025 für 2025/26), ab 1993; Prognosen und xG
    erst ab 2014. Ab 2026 je Spiel `ort`: Stadion und Kapazität wie am Spieltag, Wetter zur Spielzeit
    (art vorhersage oder gemessen, temp_c, regen_mm, regen_pct, wind_kmh, code = WMO-Wettercode).
    tipprunde = Kurzname einer Kicktipp-Tipprunde (siehe `tipprunden`): Tipps, Punkte und Bilanz nach ihrer
    Punkteregel; ohne Angabe die Standardrunde."""
    from fussballdb.api import matchday

    try:
        return _json(matchday(saison, spieltag, tipprunde))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def prognose(heim: str, gast: str) -> str:
    """Modellprognose für eine Paarung: Wahrscheinlichkeiten, erwartete Tore, wahrscheinlichste Ergebnisse,
    Über 2,5 Tore, beide treffen, Teilmodelle (Dixon-Coles, Elo), eingerechnete Ausfälle, Marktquoten."""
    return _call("predict_match", {"home": heim, "away": gast})


@mcp.tool(annotations=READ_ONLY)
def team_form(team: str, letzte_spiele: int = 8) -> str:
    """Letzte Spiele eines Teams mit Ergebnis, xG, Schüssen, Großchancen, PPDA und Durchschnittswerten.
    Die letzten Spiele können in die Vorsaison reichen (Feld saison)."""
    return _call("get_team_form", {"team": team, "last_n": letzte_spiele})


@mcp.tool(annotations=READ_ONLY)
def direkte_duelle(team_a: str, team_b: str) -> str:
    """Alle Bundesliga-Duelle zweier Teams seit 1993/94 mit Ergebnis, xG ab 2014/15."""
    return _call("get_head_to_head", {"team_a": team_a, "team_b": team_b})


@mcp.tool(annotations=READ_ONLY)
def ausfaelle(team: str) -> str:
    """Aktuelle Verletzte und Gesperrte eines Teams mit Minutenanteil und Anteil an xG+xA."""
    return _call("get_absences", {"team": team})


@mcp.tool(annotations=READ_ONLY)
def tabelle(saison: int | None = None) -> str:
    """Tabelle einer Saison mit Punkten, Toren, xG, xGA, xPts und Modell-Platz (platz_diff > 0 = steht besser
    als die Prognosen erwarten ließen), dazu die Hochrechnung zum Saisonende (prognose_platz, erw_punkte,
    p_meister, p_top4, p_abstieg in %). saison = Startjahr ab 1993 (vor 2014 ohne xG und Modell), Standard
    aktuelle Saison."""
    return _call("get_table", {"season": saison})


@mcp.tool(annotations=READ_ONLY, description="Lesende SQL-Abfrage (nur SELECT/WITH, max. 200 Zeilen) für alles, "
          "was die anderen Werkzeuge nicht abdecken. Schema:\n" + SCHEMA_HINT)
def sql(abfrage: str) -> str:
    return _call("run_sql", {"query": abfrage})


@mcp.tool(annotations=READ_ONLY)
def kickbase(spieltage: int = 3, auswahl: str = "alle", position: str | None = None, anzahl: int = 25) -> str:
    """Kickbase: erwartete Punkte je Spieler für die nächsten Spieltage mit Marktwert, Trend (7 Tage),
    Punkten pro Million, Einsatzchance und Ausfällen. auswahl: "alle", "markt" (Transfermarkt der eigenen
    Liga) oder "kader" (eigener Kader). position: TW, ABW, MF, ST."""
    from fussballdb.features.kickbase_projection import projections

    df = projections(max(1, min(spieltage, 5)))
    if df.empty:
        return "[]"
    df = df[df["kb_punkte"].notna()]
    if auswahl == "markt":
        df = df[df["markt_preis"].notna() & ~df["im_kader"]]
    elif auswahl == "kader":
        df = df[df["im_kader"]]
    if position:
        df = df[df["position"] == position.upper()]
    cols = ["name", "team_name", "position", "kb_punkte", "punkte_pro_mio", "marktwert", "trend_7t", "einsatz",
            "tore", "vorlagen", "zu_null", "ausfall", "markt_preis", "im_kader", "gegner"]
    return df.sort_values("kb_punkte", ascending=False)[cols].head(anzahl).to_json(orient="records", force_ascii=False)


@mcp.tool(annotations=READ_ONLY)
def champions_league(saison: int | None = None, runde: int | None = None) -> str:
    """Champions League: Spiele einer Runde mit Wahrscheinlichkeiten, erwarteten Toren, Tipp, Begründung,
    Europa-Elo und Kaderwerten; bei gespielten Spielen Ergebnis und Tipp-Punkte. Ohne Angaben die aktuelle
    Runde. saison = Startjahr (2026 für 2026/27), runde = Nummer aus der Rundenliste (1–8 Ligaphase,
    9 Play-offs, danach Achtelfinale bis Finale). Mit saison ohne runde: Liste der Runden."""
    from fussballdb.api import cl_round, cl_rounds

    def run():
        seasons = cl_rounds()
        if not seasons:
            raise ValueError("Keine Champions-League-Daten. Einmal `uv run fussballdb europa` ausführen.")
        if saison is not None and runde is None:
            s = next((x for x in seasons if x["season"] == saison), None)
            if s is None:
                raise ValueError(f"Saison {saison} gibt es nicht. Vorhanden: {[x['season'] for x in seasons]}")
            return s
        s = next((x for x in seasons if x["season"] == saison), seasons[0]) if saison else seasons[0]
        return cl_round(s["season"], runde or s["current_round"])

    try:
        return json.dumps(run(), default=str, ensure_ascii=False)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def cl_tabelle(saison: int | None = None) -> str:
    """Tabelle der Champions-League-Ligaphase: Punkte, Tore, Modell-Platz (platz_diff > 0 = steht besser als
    laut Prognosen erwartet) und, solange Spiele offen sind, die Hochrechnung aus 10.000 Simulationen:
    prognose_platz, erw_punkte, p_achtelfinale (Platz 1–8), p_playoffs (9–24), p_aus (25–36) in %.
    saison = Startjahr, Standard aktuelle Saison."""
    from fussballdb.api import cl_rounds, cl_table

    try:
        season = saison or cl_rounds()[0]["season"]
        return json.dumps(cl_table(season), default=str, ensure_ascii=False)
    except (ValueError, IndexError) as exc:
        raise ToolError(str(exc) or "Keine Champions-League-Daten.") from exc


@mcp.tool(annotations=READ_ONLY)
def wettbewerb(wettbewerb: str = "D2", saison: int | None = None, runde: int | None = None) -> str:
    """Runde der 2. Bundesliga (wettbewerb="D2"), des DFB-Pokals ("DFB") oder der Champions League ("CL") mit
    Wahrscheinlichkeiten, erwarteten Toren, Tipp und Begründung. Ohne saison/runde die aktuelle Runde; mit saison
    allein die Rundenliste. Grundlage: Elo und Dixon-Coles über alle Ligen, Kaderwert als Startwert. Ab 2026
    je Spiel `ort` mit Stadion, Kapazität und Wetter wie bei `spieltag`."""
    from fussballdb.api import comp_round, comp_rounds

    try:
        seasons = comp_rounds(wettbewerb)
        if saison is not None and runde is None:
            s = next((x for x in seasons if x["season"] == saison), None)
            if s is None:
                raise ValueError(f"Saison {saison} gibt es nicht. Vorhanden: {[x['season'] for x in seasons]}")
            return json.dumps(s, default=str, ensure_ascii=False)
        s = next((x for x in seasons if x["season"] == saison), seasons[0]) if saison else seasons[0]
        return json.dumps(comp_round(wettbewerb, s["season"], runde or s["current_round"]), default=str, ensure_ascii=False)
    except (ValueError, IndexError) as exc:
        raise ToolError(str(exc) or "Keine Daten.") from exc


@mcp.tool(annotations=READ_ONLY)
def tabelle_2_liga(saison: int | None = None) -> str:
    """Tabelle der 2. Bundesliga mit Modell-Platz und Hochrechnung (prognose_platz, erw_punkte, p_aufstieg,
    p_relegation_oben, p_relegation_unten, p_abstieg in %). saison = Startjahr, Standard aktuelle Saison."""
    from fussballdb.api import comp_rounds, comp_table

    try:
        return json.dumps(comp_table("D2", saison or comp_rounds("D2")[0]["season"]), default=str, ensure_ascii=False)
    except (ValueError, IndexError) as exc:
        raise ToolError(str(exc) or "Keine Daten.") from exc


@mcp.tool(annotations=READ_ONLY)
def spielberichte(frage: str = "", team: str | None = None, saison: int | None = None, anzahl: int = 8,
                  neueste_zuerst: bool = False) -> str:
    """Spielberichte der Bundesliga ab 2014/15 im Zeitungsstil durchsuchen (Tore mit Minute, Schütze, Vorlage und
    Art, Pfosten und vergebene Chancen, Tabelle und Serien, Statistik, Einordnung, Stichworte wie Comeback, spätes Siegtor, Platzverweis, Überraschung). Kombinierte Suche nach
    Bedeutung und Wörtern; team (auch umgangssprachlich) und saison (Startjahr) filtern, ohne frage die jüngsten
    Spiele. Für Fragen zu Spielverläufen und für Zusammenfassungen; die Berichte enthalten nur Fakten aus den
    Daten, nichts darüber hinaus erfinden. Für Zählfragen ("wie oft") ist `sql` genauer. Bei "wann zuletzt …"
    neueste_zuerst=true (die jüngsten Treffer statt der relevantesten)."""
    from fussballdb.api import search_reports

    try:
        return _json(search_reports(frage, team, saison, max(1, min(anzahl, 20)), neueste_zuerst))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def tipprunden(runde: str | None = None) -> str:
    """Kicktipp-Tipprunden mit Punkteregel (Sieg Tendenz/Tordifferenz/exakt, Remis Tendenz), Tippschluss und
    Extratipps. Mit runde (Kurzname): zusätzlich die Bonusfragen (Extratipps) mit den wahrscheinlichsten Antworten
    in %: `prognose` mit dem Wissen zum Tippschluss (Modell und Saisonsimulation nur mit Daten bis dahin; so hätte
    man tippen sollen), `heute` mit dem aktuellen Stand, `antworten` wenn schon entschieden. Der erste
    Trainerwechsel ist nur eine Näherung (wer nach dem 8. Spieltag unten steht); das Team des Torschützenkönigs
    kommt aus den Torraten der Spieler, der `hinweis` nennt die Favoriten. Tipps je Runde liefert
    `spieltag` mit `tipprunde`."""
    from fussballdb.api import tip_round_bonus, tip_rounds

    try:
        return _json(tip_round_bonus(runde) if runde else tip_rounds())
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def anreise(team: str, start: str | None = None) -> str:
    """Anreise mit Bus und Bahn zum nächsten Spiel eines Teams (Bundesliga, 2. Liga, Pokal, CL): Stadion,
    Anstoß, Ankunftszeit (eine Stunde vor dem Anpfiff, Ortszeit am Stadion) und ein Google-Maps-Link mit
    ÖPNV-Verbindungen. start = wo der Nutzer gerade ist (Adresse, Ort oder "lat,lon"); ohne start nimmt die
    Google-Maps-App den aktuellen Standort. Den Link `url` unverändert weitergeben; `url_ohne_zeit` ist der
    Rückfall ohne Ankunftszeit. Spielorte gibt es für Spiele der nächsten 14 Tage."""
    from fussballdb.assistant.tools import _rows
    from fussballdb.ingest.venues import route

    team_id = _tb().teams.find(team)
    q = f"%{team.strip()}%"
    rows = _rows(
        """
        SELECT * FROM (
            SELECT 'Bundesliga' AS wettbewerb, m.kickoff, ht.name AS heim, at.name AS gast, v.*
            FROM match m JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            JOIN match_venue v ON v.competition = 'BL' AND v.match_id = m.id
            WHERE NOT m.finished AND m.kickoff > now() AND :tid IN (m.home_team_id, m.away_team_id)
            UNION ALL
            SELECT CASE e.competition WHEN 'CL' THEN 'Champions League' WHEN 'D2' THEN '2. Bundesliga'
                   ELSE 'DFB-Pokal' END, e.kickoff, ht.name, at.name, v.*
            FROM eu_match e JOIN eu_team ht ON ht.id = e.home_id JOIN eu_team at ON at.id = e.away_id
            JOIN match_venue v ON v.competition = e.competition AND v.match_id = e.id
            WHERE NOT e.finished AND e.kickoff > now() AND EXISTS (
                SELECT 1 FROM eu_team t LEFT JOIN eu_team_alias a ON a.team_id = t.id
                WHERE t.id IN (e.home_id, e.away_id) AND (t.name ILIKE :q OR a.alias ILIKE :q))
        ) x ORDER BY kickoff LIMIT 1
        """, tid=team_id or -1, q=q)
    if not rows:
        raise ToolError(f"Kein Spiel von {team!r} mit Spielort in den nächsten 14 Tagen gefunden.")
    r = rows[0]
    if r["lat"] is None:
        raise ToolError(f"Für {r['heim']} – {r['gast']} fehlen die Koordinaten des Stadions.")
    return json.dumps({"spiel": f"{r['heim']} – {r['gast']}", "wettbewerb": r["wettbewerb"],
                       "anstoss": r["kickoff"].astimezone().isoformat(timespec="minutes"),
                       "stadion": r["stadium"], "stadt": r["city"], "kapazitaet": r["capacity"],
                       **{k: v for k, v in route(r["lat"], r["lon"], r["kickoff"], r["country"], start or "").items()
                          if k != "url_vorlage"}},
                      ensure_ascii=False, default=str)


@mcp.tool(annotations=READ_ONLY)
def datenstand() -> str:
    """Wie aktuell sind die Daten? Zeigt pro Bereich (Ergebnisse, Ausfälle, Quoten, Prognosen …), ob ein
    Update nötig wäre und wann zuletzt aktualisiert wurde. Steht bei einem Bereich ein `hint`, fehlen die Daten
    nur, weil die Quelle sie noch nicht bereitgestellt hat: kein Fehler, den Hinweis so weitergeben."""
    from fussballdb.maintenance import check

    return json.dumps(check(), default=str, ensure_ascii=False)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
