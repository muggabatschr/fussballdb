from typing import Annotated

import typer
from rich.console import Console

from fussballdb.config import DEFAULT_SEASONS

app = typer.Typer(help="Bundesliga-Datenbank: Import, Modell, Prognosen und Chat.", no_args_is_help=True)
console = Console()

SeasonsOpt = Annotated[
    list[int] | None,
    typer.Option("--season", "-s", help="Startjahr der Saison, z. B. 2026 für 2026/27. Mehrfach möglich."),
]


@app.command("init-db")
def init_db() -> None:
    """Tabellen anlegen und Teams/Aliase einspielen."""
    from sqlalchemy import text

    from fussballdb.db.models import MIGRATIONS, Base
    from fussballdb.db.session import engine, session_scope
    from fussballdb.ingest.team_mapping import seed_teams

    Base.metadata.create_all(engine)
    with session_scope() as s:
        for stmt in MIGRATIONS:
            s.execute(text(stmt))
        seed_teams(s)
    console.print("[green]Datenbank bereit.[/]")


@app.command()
def ingest(
    seasons: SeasonsOpt = None,
    details: Annotated[bool, typer.Option(help="Schüsse und Kader je Spiel von Understat laden (langsam beim ersten Mal)")] = True,
) -> None:
    """Spielplan, Ergebnisse, Statistiken, Quoten und xG importieren."""
    from fussballdb.db.session import session_scope
    from fussballdb.ingest import football_data, openligadb, understat

    for year in seasons or DEFAULT_SEASONS:
        label = f"{year}/{(year + 1) % 100:02d}"
        with session_scope() as s:
            n = openligadb.ingest_season(s, year)
        console.print(f"{label} OpenLigaDB: {n} Spiele")
        with session_scope() as s:
            n, missing = football_data.ingest_season(s, year)
        console.print(f"{label} football-data: {n} Spiele")
        for m in missing:
            console.print(f"  [yellow]nicht zugeordnet:[/] {m}")
        with session_scope() as s:
            n, missing = understat.ingest_season(s, year, with_shots=details)
        console.print(f"{label} Understat: {n} Spiele")
        for m in missing:
            console.print(f"  [yellow]nicht zugeordnet:[/] {m}")



@app.command()
def snapshot() -> None:
    """Täglicher Schnappschuss: Verletzte/Sperren und Aufstellungen (voraussichtlich bzw. gespielt)."""
    from fussballdb.db.session import session_scope
    from fussballdb.ingest import lineups

    absences()
    with session_scope() as s:
        st = lineups.ingest(s)
    console.print(f"Aufstellungen: {st['teams']} Teams ({st['vorschau']} Vorschau, {st['gespielt']} gespielt), "
                  f"{st['ohne_spieler_zuordnung']} Spieler ohne Understat-Zuordnung")
    for slug in st["ohne_team"]:
        console.print(f"  [yellow]Team nicht zugeordnet:[/] {slug}")
    for err in st["fehler"]:
        console.print(f"  [red]{err}[/]")


@app.command("verletzungshistorie")
def verletzungshistorie() -> None:
    """Verletzungshistorie aller Spieler seit 2023/24 laden (beim ersten Mal ~40 Min., danach aus dem Cache)."""
    from fussballdb.maintenance import ensure as run_ensure

    run_ensure(only={"verletzungshistorie"}, log=console.print)


@app.command()
def logos(force: Annotated[bool, typer.Option(help="Vorhandene Logos neu laden")] = False) -> None:
    """Vereinswappen für die Web-App laden (web/public/logos, Zuordnung in web/src/lib/logos.json)."""
    from fussballdb.db.session import session_scope
    from fussballdb.ingest import logos as logos_ingest

    with session_scope() as s:
        res = logos_ingest.ingest(s, force)
    console.print(f"Logos: {res['quellen']}")
    for name in res["fehlen"]:
        console.print(f"  [yellow]kein Logo gefunden:[/] {name}")


@app.command("kickbase-login")
def kickbase_login() -> None:
    """Bei Kickbase anmelden (E-Mail und Passwort werden nur hier abgefragt, gespeichert wird nur das Token)."""
    from fussballdb.ingest import kickbase

    email = typer.prompt("Kickbase-E-Mail")
    password = typer.prompt("Kickbase-Passwort", hide_input=True)
    try:
        info = kickbase.login(email, password)
    except kickbase.KickbaseAuthError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"[green]Angemeldet.[/] Token gültig bis {info['expires'] or 'unbekannt'}, gespeichert in {kickbase.TOKEN_FILE}")
    for league in info["leagues"]:
        console.print(f"  Liga: {league['name']} (id {league['id']})")


@app.command()
def kickbase(
    historie: Annotated[bool, typer.Option(help="Punkte- und Marktwert-Verlauf mitladen")] = True,
) -> None:
    """Kickbase-Daten laden: alle Spieler (Marktwert, Punkte, Verlauf) und Markt/Kader der eigenen Liga."""
    from fussballdb.db.session import session_scope
    from fussballdb.ingest import kickbase as kb

    try:
        with session_scope() as s:
            st = kb.ingest_league(s)
        console.print(f"Liga: {st['markt']} Spieler auf dem Transfermarkt, {st['kader']} im eigenen Kader")
        with session_scope() as s:
            st = kb.ingest_players(s, history=historie, progress=lambda tid, n: print(f"Team {tid}: {n} Spieler", flush=True))
        console.print(f"[green]{st['spieler']} Spieler[/] ({st['zugeordnet']} Understat zugeordnet), "
                      f"{st['punkte']} Punkte-Einträge, {st['marktwerte']} Marktwerte")
    except kb.KickbaseAuthError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


@app.command("kaderwerte")
def kaderwerte(
    start: Annotated[str, typer.Option(help="Erster Stichtag (JJJJ-MM-TT)")] = "2023-07-01",
) -> None:
    """Kaderwerte von Transfermarkt zum 1. jedes Monats laden (alte Stichtage werden gecacht)."""
    from datetime import date

    from fussballdb.db.session import session_scope
    from fussballdb.ingest import squad_values

    with session_scope() as s:
        n, _ = squad_values.ingest(s, date.fromisoformat(start))
    console.print(f"{n} Kaderwerte gespeichert.")


@app.command()
def absences() -> None:
    """Aktuelle Verletzte (Transfermarkt) und Sperren (aus Karten) aktualisieren."""
    from fussballdb.db.session import session_scope
    from fussballdb.ingest import absences as absences_ingest

    with session_scope() as s:
        stats = absences_ingest.ingest(s)
    console.print(f"Verletzte: {stats['injuries']}, Sperren: {stats['suspensions']}")
    for name in stats["unmatched_players"]:
        console.print(f"  [yellow]ohne Understat-Zuordnung:[/] {name}")



@app.command()
def predict(
    matchdays: Annotated[int, typer.Option("--matchdays", "-n", help="Wie viele kommende Spieltage anzeigen")] = 1,
) -> None:
    """Prognosen für alle offenen Spiele der Saison speichern und die nächsten Spieltage anzeigen."""
    from rich.table import Table

    from fussballdb.model.predict import predict_upcoming

    df = predict_upcoming()
    if not df.empty:
        df = df[df["spieltag"] < df["spieltag"].min() + matchdays]
    if df.empty:
        console.print("Keine kommenden Spiele gefunden.")
        return
    table = Table(title="Prognose (Dixon-Coles + Elo, inkl. Ausfälle)")
    for col in ("ST", "Anstoß", "Heim", "Gast", "1", "X", "2", "xTore", ">2,5", "Ausfälle Stammspieler"):
        table.add_column(col)
    for r in df.itertuples():
        missing = "; ".join(x for x in (r.ausfaelle_heim, r.ausfaelle_gast) if x)
        table.add_row(str(r.spieltag), r.anstoss.tz_convert("Europe/Berlin").strftime("%a %d.%m. %H:%M"),
                      r.heim, r.gast, f"{r.p_home:.0%}", f"{r.p_draw:.0%}", f"{r.p_away:.0%}",
                      f"{r.exp_home_goals:.1f}:{r.exp_away_goals:.1f}", f"{r.p_over25:.0%}", missing)
    console.print(table)


@app.command()
def backfill(
    seasons: SeasonsOpt = None,
    force: Annotated[bool, typer.Option(help="Vorhandene Rückblick-Prognosen neu berechnen (Live-Prognosen bleiben)")] = False,
) -> None:
    """Rückblick-Prognosen für gespielte Spieltage nur mit den Daten vor dem jeweiligen Spieltag."""
    from fussballdb.model.predict import backfill as run_backfill

    n = run_backfill(seasons, force, progress=lambda y, md, k: console.print(f"{y}/{(y + 1) % 100:02d} Spieltag {md}: {k}"))
    console.print(f"[green]{n} Prognosen gespeichert.[/]")


@app.command()
def backtest(
    seasons: SeasonsOpt = None,
    ausfaelle: Annotated[str, typer.Option(help="verletzte (wie das Modell), keine, aufstellung (Obergrenze, Wissen aus der Zukunft)")] = "verletzte",
) -> None:
    """Modell Spieltag für Spieltag rückwirkend testen und mit dem Wettmarkt vergleichen."""
    from fussballdb.model.evaluate import backtest as run_backtest

    res, _ = run_backtest(seasons or [2025, 2026], absences=ausfaelle)
    console.print(res.round(4).to_string(index=False))
    console.print("RPS/Brier/Log-Loss: kleiner ist besser. Markt = Durchschnittsquoten ohne Buchmachermarge.")


@app.command()
def europa(
    werte: Annotated[bool, typer.Option(help="Kaderwerte von Transfermarkt laden (beim ersten Mal ~25 Min.)")] = True,
) -> None:
    """CL, 2. Liga, Pokal: Europapokal-, Liga- und Pokalspiele, xG (Understat, FotMob), Kaderwerte und Wappen laden."""
    from fussballdb.db.session import session_scope
    from fussballdb.ingest import europe

    with session_scope() as s:
        console.print(f"Europapokal: {europe.ingest_euro(s)} Spiele")
    with session_scope() as s:
        console.print(f"Ligen: {europe.ingest_domestic(s, list(range(europe.FIRST_SEASON, max(DEFAULT_SEASONS) + 1)))} Spiele")
    with session_scope() as s:
        n_de = europe.ingest_germany(s, list(range(europe.FIRST_SEASON, max(DEFAULT_SEASONS) + 1)))
    console.print(f"2. Liga, 3. Liga, DFB-Pokal: {n_de} Spiele")
    if werte:
        with session_scope() as s:
            n, unknown = europe.ingest_values(s, log=console.print)
        console.print(f"Kaderwerte: {n}")
        for country, clubs in unknown.items():
            console.print(f"  [dim]{country} ohne Zuordnung (nicht benötigt, solange nie im Europapokal): {len(clubs)}[/]")
    from fussballdb.ingest import cl_xg

    with session_scope() as s:
        res_league = europe.ingest_league_xg(s, list(range(europe.FIRST_SEASON, max(DEFAULT_SEASONS) + 1)),
                                             log=lambda m: None)
    console.print(f"Liga-xG (Understat): {res_league['mit_xg']} Spiele")
    with session_scope() as s:
        res_xg = cl_xg.ingest(s, sorted({y for _, _, y in europe.EURO_COMPETITIONS}), log=console.print)
    console.print(f"CL-xG: {res_xg['mit_xg']} Spiele" + (f", ohne Zuordnung: {', '.join(res_xg['nicht_zugeordnet'])}"
                                                       if res_xg["nicht_zugeordnet"] else ""))
    with session_scope() as s:
        res = europe.ingest_logos(s)
    console.print(f"Wappen: {res['geladen']} neu" + (f", fehlen: {', '.join(res['fehlen'])}" if res["fehlen"] else ""))


@app.command("cl-test")
def cl_test() -> None:
    """Champions-League-Prognose rückwirkend testen: jede Runde nur mit dem Stand vor ihrem ersten Anpfiff."""
    from fussballdb.model.europe import backtest as run

    res = run(log=lambda m: None)
    cols = [c for c in res.columns if c.startswith(("rps_", "ll_"))]
    by_season = res.groupby("season")[cols + ["punkte"]].mean()
    by_season["spiele"] = res.groupby("season").size()
    console.print(by_season.round(4).to_string())
    console.print("\nGesamt:")
    console.print(res[cols + ["punkte"]].mean().round(4).to_string())
    console.print("RPS/Log-Loss: kleiner ist besser. Punkte = Kicktipp-Punkte je Spiel nach der Regel der Tipprunde.")


@app.command("cl-prognosen")
def cl_prognosen(
    force: Annotated[bool, typer.Option(help="Rückblick-Prognosen neu berechnen")] = False,
    wettbewerb: Annotated[str | None, typer.Option(help="CL, D2 (2. Bundesliga) oder DFB (Pokal); Standard: alle")] = None,
) -> None:
    """CL, 2. Bundesliga, DFB-Pokal: Rückblick-Prognosen für gespielte Runden, Live-Prognosen für offene Spiele."""
    from fussballdb.model.europe import PREDICTED_COMPETITIONS, backfill, predict_upcoming

    for comp in [wettbewerb.upper()] if wettbewerb else PREDICTED_COMPETITIONS:
        console.print(f"{comp}: Rückblick {backfill(comp, force=force)}, Live {predict_upcoming(comp)} Prognosen")


@app.command("abschluss-test")
def abschluss_test(
    kombi: Annotated[bool, typer.Option(help="Zusammen mit den einzeln verworfenen Erweiterungen testen (~10 Min.)")] = False,
) -> None:
    """Über-/Unterperformance (Tore gegenüber xG der letzten Spiele) im Rückblick-Test, 2016–2026."""
    from fussballdb.model.evaluate import compare_finishing, compare_finishing_combo

    progress = lambda y, md: md == 34 and console.print(f"{y}/{(y + 1) % 100:02d} fertig")  # noqa: E731
    res = compare_finishing_combo(progress=progress) if kombi else compare_finishing(progress=progress)
    console.print(res.round(5).to_string(index=False))
    console.print("delta < 0 = besser. Übernommen wird nur, was im Test in mindestens ~90 % der Ziehungen besser ist.")


@app.command()
def erinnerung(
    stunden: Annotated[float, typer.Option(help="So viele Stunden vor dem ersten Anpfiff erinnern")] = 3.0,
    test: Annotated[bool, typer.Option(help="Sofort eine Mitteilung schicken (zum Ausprobieren)")] = False,
) -> None:
    """Mac-Mitteilung mit den Tipps, wenn der nächste Bundesliga-Spieltag bald beginnt (einmal je Spieltag).
    Läuft alle 30 Minuten per launchd (scripts/de.fussballdb.erinnerung.plist)."""
    from fussballdb.reminder import remind

    console.print(remind(hours=stunden, force=test))


@app.command("belastung-test")
def belastung_test(tage: Annotated[int, typer.Option(help="Europapokalspiel höchstens so viele Tage vorher")] = 4) -> None:
    """Europapokal-Belastung im Rückblick-Test (Bundesliga 2024–2026): Torerwartung nach Europapokalspiel senken."""
    from fussballdb.model.evaluate import compare_euro_load

    console.print(compare_euro_load(days=tage).round(5).to_string(index=False))
    console.print("delta < 0 = besser. besser_pct: Bootstrap über die Spiele mit Belastung.")


@app.command("cl-xg-test")
def cl_xg_test() -> None:
    """CL: europaweites xG-Modell (Dixon-Coles, Form, Mischung mit Elo) gegen die bisherige Elo, Rückblick-Test."""
    from fussballdb.model.europe import backtest_xg, compare_xg

    res = backtest_xg(log=lambda m: None)
    console.print(compare_xg(res).round(4).to_string(index=False))
    console.print(res.groupby("season")[[c for c in res.columns if c.startswith("rps|")]].mean().round(4).T.to_string())


@app.command("xg-varianten")
def xg_varianten(seasons: SeasonsOpt = None) -> None:
    """xG-Varianten (xG, npxG, Spielstand-bereinigt, Rote Karten) im Rückblick-Test vergleichen."""
    from fussballdb.model.evaluate import compare_xg_variants

    res = compare_xg_variants(seasons or [2024, 2025, 2026])
    console.print(res.round(4).to_string(index=False))
    console.print("RPS: kleiner ist besser. Unterschiede unter ~0,0005 sind meist Zufall.")


@app.command("kaderwert-test")
def kaderwert_test() -> None:
    """Kaderwert als Startstärke im Rückblick-Test (eingestellt an 2024/25, getestet an 2025–2026)."""
    from fussballdb.model.evaluate import compare_squad_value

    console.print(compare_squad_value().round(4).to_string(index=False))
    console.print("k = Gewicht des Kaderwerts, ridge = Dämpfung. st1_8 = nur Spieltage 1 bis 8.")


@app.command("erweiterungen-test")
def erweiterungen_test() -> None:
    """Form, Heimvorteil je Team und direkte Duelle im Rückblick-Test gegen das aktuelle Modell."""
    from fussballdb.model.evaluate import compare_extras

    console.print(compare_extras().round(5).to_string(index=False))
    console.print("delta < 0 = besser als das aktuelle Modell. Eingestellt an 2024/25, getestet an 2025–2026.")


@app.command("verletzungen-test")
def verletzungen_test() -> None:
    """Ausfälle aus der Transfermarkt-Verletzungshistorie im Rückblick-Test."""
    from fussballdb.model.evaluate import compare_injuries

    console.print(compare_injuries().round(5).to_string(index=False))


@app.command("kombi-test")
def kombi_test() -> None:
    """Alle Erweiterungen zusammen und jeweils eine weggelassen (eingestellt 2016–2020, getestet 2021–2026)."""
    from fussballdb.model.evaluate import compare_combo

    console.print(compare_combo().round(5).to_string(index=False))
    console.print("delta < 0 = besser als das aktuelle Modell. saisons_besser = in wie vielen Saisons besser.")


@app.command("tipp-test")
def tipp_test() -> None:
    """Bisheriger Tipp gegen Tipp nach erwarteten Kicktipp-Punkten (Rückblick)."""
    from fussballdb.model.evaluate import compare_tips

    console.print(compare_tips().round(3).to_string(index=False))


@app.command("kalibrierung")
def kalibrierung() -> None:
    """Gespeicherte Rückblick-Prognosen: vorhergesagte gegen eingetretene Häufigkeiten."""
    import pandas as pd
    from sqlalchemy import text

    from fussballdb.db.session import engine

    df = pd.read_sql(text("""SELECT p.p_home, p.p_draw, p.p_away, p.p_over25, m.home_goals hg, m.away_goals ag
        FROM prediction p JOIN match m ON m.id = p.match_id WHERE m.finished AND p.basis = 'rueckblick'"""), engine)
    checks = [("Heimsieg", "p_home", df.hg > df.ag), ("Remis", "p_draw", df.hg == df.ag),
              ("Auswärtssieg", "p_away", df.hg < df.ag), ("Über 2,5", "p_over25", df.hg + df.ag > 2.5)]
    console.print(f"{len(df)} Spiele")
    for label, col, hit in checks:
        console.print(f"{label:13s} vorhergesagt {df[col].mean():.3f}  eingetreten {hit.mean():.3f}")


@app.command()
def ensure(
    voll: Annotated[bool, typer.Option("--voll", help="Alle Schritte ausführen, auch wenn die Daten aktuell sind")] = False,
    ohne_langsame: Annotated[bool, typer.Option(help="Langsame Schritte auslassen (Verletzungshistorie, Kickbase-Punkte)")] = False,
) -> None:
    """Prüfen, ob Daten fehlen oder veraltet sind, und nur die nötigen Schritte ausführen."""
    from fussballdb.maintenance import ensure as run_ensure

    results = run_ensure(force=voll, include_slow=not ohne_langsame, log=console.print)
    done = [r for r in results if r["status"] == "ok"]
    console.print(f"[green]Fertig.[/] {len(done)} Schritt(e) ausgeführt, "
                  f"{sum(r['status'] == 'aktuell' for r in results)} bereits aktuell.")
    try:
        import httpx

        if done:
            httpx.post("http://127.0.0.1:8000/reload", timeout=5)
    except httpx.HTTPError:
        pass  # API läuft nicht, nichts zu tun


@app.command()
def status() -> None:
    """Zeigt, welche Daten aktuell sind und welche Update-Schritte nötig wären."""
    from fussballdb.maintenance import check

    for c in check():
        state = "[green]aktuell[/]" if not c["reason"] else ("[yellow]wartet[/]" if c["waiting"] else "[red]nötig[/]")
        if c["hint"]:
            state = "[cyan]noch nicht da[/]"
        last = f"zuletzt {c['last_run']:%d.%m. %H:%M}" if c["last_run"] else "noch nie"
        console.print(f"{c['label']:30s} {state:20s} {c['reason'] or ''}  ({last})")
        if c["hint"]:
            console.print(f"{'':31s}[cyan]{c['hint']}[/]")


@app.command()
def update(
    details: Annotated[bool, typer.Option(help="Schüsse und Kader laden")] = True,
) -> None:
    """Vollständiges Update aller Schritte (wie `ensure --voll --ohne-langsame`)."""
    ensure(voll=True, ohne_langsame=True)


@app.command()
def chat(
    question: Annotated[str | None, typer.Argument(help="Einzelne Frage; ohne Angabe interaktiver Modus")] = None,
    provider: Annotated[str | None, typer.Option(help="local (Standard) oder anthropic")] = None,
    effort: Annotated[str, typer.Option(help="Nur Claude: low | medium | high")] = "medium",
) -> None:
    """Fragen an ein Sprachmodell stellen, das über Werkzeuge auf Datenbank und Prognosemodell zugreift."""
    from rich.markdown import Markdown

    from fussballdb.assistant.chat import create_chat
    from fussballdb.config import LLM_PROVIDER

    try:
        session = create_chat(provider or LLM_PROVIDER, effort)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    on_tool = lambda name, args: console.print(f"[dim]→ {name} {args}[/]")
    if question:
        console.print(Markdown(session.ask(question, on_tool)))
        return
    console.print("Frage stellen, leere Zeile beendet.")
    while q := console.input("[bold]> [/]").strip():
        console.print(Markdown(session.ask(q, on_tool)))



@app.command()
def serve(
    host: Annotated[str, typer.Option(help="0.0.0.0 nur, wenn die API im Netz erreichbar sein soll")] = "127.0.0.1",
    port: int = 8000,
) -> None:
    """REST-API für die Web-App starten (Doku unter /docs)."""
    import uvicorn

    uvicorn.run("fussballdb.api:app", host=host, port=port)


if __name__ == "__main__":
    app()
