"""MCP-Server: macht Datenbank und Prognosemodell für Claude Desktop und Claude Code nutzbar.

Claude ruft diese Werkzeuge auf, es wird kein API-Schlüssel benötigt; abgerechnet wird über das
Claude-Abo. Start über stdio (`uv run fussballdb-mcp`), die Datenbank muss laufen (docker compose)."""

import json

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from fussballdb.assistant.tools import SCHEMA_HINT, Toolbox, _json

INSTRUCTIONS = """Daten und Prognosen zur 1. Fußball-Bundesliga seit 2014/15, zur Champions League (ab 2024/25,
Werkzeug `champions_league`) und zu Kickbase: Ergebnisse, xG, Schüsse,
Großchancen, PPDA, Kader, Verletzte, Kaderwerte, Wettquoten sowie ein statistisches Prognosemodell
(Dixon-Coles auf xG mit Formkomponente + Elo, Kaderwert als Startstärke, Verletzte eingerechnet).

- Wahrscheinlichkeiten nur aus `prognose`, `naechste_spiele` oder `spieltag` übernehmen, nie selbst schätzen.
  Einordnen (Form, Ausfälle, Marktquoten) ist erwünscht, die Zahlen nicht verändern.
- Verletzte sind in den Wahrscheinlichkeiten bereits eingerechnet.
- Der Tipp ist das Ergebnis mit den meisten erwarteten Punkten nach der Punkteregel der Tipprunde.
- Prognosen sind Wahrscheinlichkeiten, keine Wettempfehlung. Ballbesitz liegt nicht vor.
- Teamnamen dürfen umgangssprachlich sein (BVB, Gladbach, Bayern)."""

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
def spieltag(saison: int, spieltag: int) -> str:
    """Alle Spiele eines Spieltags mit Ergebnis, xG, Prognose, Tipp des Modells und Tipp-Punkten sowie
    der Bilanz des Spieltags und der Saison. saison = Startjahr (2025 für 2025/26), ab 2014."""
    from fussballdb.api import matchday

    return _json(matchday(saison, spieltag))


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
    """Alle Duelle zweier Teams seit 2014/15 mit Ergebnis und xG."""
    return _call("get_head_to_head", {"team_a": team_a, "team_b": team_b})


@mcp.tool(annotations=READ_ONLY)
def ausfaelle(team: str) -> str:
    """Aktuelle Verletzte und Gesperrte eines Teams mit Minutenanteil und Anteil an xG+xA."""
    return _call("get_absences", {"team": team})


@mcp.tool(annotations=READ_ONLY)
def tabelle(saison: int | None = None) -> str:
    """Tabelle einer Saison mit Punkten, Toren, xG, xGA, xPts und Modell-Platz (platz_diff > 0 = steht besser
    als die Prognosen erwarten ließen), dazu die Hochrechnung zum Saisonende (prognose_platz, erw_punkte,
    p_meister, p_top4, p_abstieg in %). saison = Startjahr, Standard aktuelle Saison."""
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
