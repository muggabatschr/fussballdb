# fussballdb

Datenbank für die 1. Bundesliga mit Ergebnissen, xG, Schüssen, Großchancen, Kadern, Ausfällen und
Wettquoten seit 2014/15 (ab dann gibt es xG bei Understat). Dazu ein Prognosemodell für die nächsten Spiele und ein Chat, in dem ein Sprachmodell
die Daten abfragt und erklärt.

Was es alles gibt:

- **Datenbank** (PostgreSQL in Docker) mit allen Spielen seit 2014/15, Spielerdaten, Verletzungen,
  Sperren, Kaderwerten und Quoten
- **Prognosemodell** mit Wahrscheinlichkeiten, erwarteten Toren und einem Tipp nach der Punkteregel der
  Kicktipp-Runde, für kommende Spiele und im Rückblick mit dem damaligen Datenstand
- **Web-App** mit Spieltagen, Tabelle, Teamseiten, Chat und einem Kickbase-Tab
- **Chat** mit einem lokalen Sprachmodell (LM Studio, ohne Cloud)
- **MCP-Server** und Skill `/fussball`, damit Claude direkt auf die Daten zugreift
- **Automatisches Update** beim Start der App und täglich per launchd

## Aufbau

```
Quellen ──► Import ──► PostgreSQL ──► Modell (Dixon-Coles + Elo + Kaderwert) ──► prediction
                              │                                     │
                              └────────── Chat (LLM + Tools)   ◄───┘
```

### Projektstruktur

```
fussballdb/
├── docker-compose.yml         # db (immer), api + web (Profil "app")
├── Dockerfile                 # API-Container (Python 3.12 + uv)
├── scripts/
│   ├── install.sh             # komplette Einrichtung aus dem Repo
│   ├── update.sh              # Update-Einstieg (startet bei Bedarf Docker), ruft `fussballdb ensure`
│   └── de.fussballdb.snapshot.plist   # launchd-Vorlage: täglich 9:30
├── src/fussballdb/
│   ├── cli.py                 # alle Befehle (`fussballdb …`)
│   ├── config.py              # Saisons, LLM, Punkteregel aus .env
│   ├── maintenance.py         # prüft und führt Update-Schritte aus (ensure/status)
│   ├── api.py                 # FastAPI für die Web-App
│   ├── mcp_server.py          # MCP-Server für Claude
│   ├── db/                    # Tabellen (models.py), Verbindung
│   ├── ingest/                # Importer je Quelle, Team-Zuordnung, HTTP mit Cache und Wiederholung
│   ├── features/              # Ausfälle (availability), Kickbase-Punkte und -Prognose, verworfene Tests
│   ├── model/                 # Dixon-Coles, Elo, Ensemble, Prognosen, Begründung, Backtests
│   └── assistant/             # Chat-Werkzeuge und lokaler Chat
├── web/                       # Next.js-App
└── tests/
```

Der Chat läuft standardmäßig mit einem **lokalen Modell** (LM Studio/Bionic oder Ollama), alles bleibt auf
dem Rechner. Claude ist optional. Das Sprachmodell rechnet keine Wahrscheinlichkeiten selbst. Es holt sie über Werkzeuge aus dem
Modell und der Datenbank (Retrieval) und erklärt sie. So bleiben die Zahlen nachvollziehbar und
lassen sich im Backtest prüfen.

## Datenquellen (alle kostenlos)

| Quelle | Daten |
|---|---|
| [OpenLigaDB](https://www.openligadb.de) | Spielplan, Ergebnisse, Halbzeit, Spieltage |
| [football-data.co.uk](https://www.football-data.co.uk) | Schüsse, aufs Tor, Ecken, Fouls, Karten, Quoten (B365, Pinnacle, Betfair, Ø, Max; Eröffnung und Schluss), Vorab-Quoten |
| [Understat](https://understat.com) | xG, npxG, xPts, PPDA, Deep, jeder Schuss mit xG, Kader je Spiel mit Minuten/xG/xA |
| [Transfermarkt](https://www.transfermarkt.de) | aktuelle Verletzte und Kranke, Verletzungshistorie je Spieler, Kaderwerte zum 1. jedes Monats |
| [Ligainsider](https://www.ligainsider.de) | voraussichtliche Aufstellungen vor dem Spiel, tatsächliche danach |
| [Kickbase](https://www.kickbase.com) (inoffizielle API, eigenes Konto) | Punkte, Marktwerte, Status, Markt und Kader der eigenen Liga |

Abgeleitet:
- **Tore und Vorlagen je Spieler** aus den Understat-Kadern (`player_match`)
- **Großchancen** = Schüsse mit xG ≥ 0,3
- **Sperren** = Rot/Gelb-Rot im letzten Spiel oder 5./10./15. Gelbe Karte
- **Elo** je Team und Spiel

Nicht verfügbar: **Ballbesitz**. FBref, Sofascore und FotMob blocken automatisierte Abrufe, die Spalte
`possession` bleibt leer.

Hinweise zu den Daten:
- Union – Bochum (14.12.2024) steht in `match` mit dem Sportgerichtsurteil 0:2, in den Statistiken mit dem gespielten 1:1.
- Understat-Spiel-xG ist nicht die Summe der Schuss-xG (Nachschüsse im selben Angriff werden gedeckelt).

## Einrichtung

Die Datenbank selbst legt Docker an (Postgres mit pgvector, Benutzer, Passwort und Datenbank stehen in
`docker-compose.yml`, die Daten liegen im Docker-Volume `pgdata`). Alles Weitere erledigt ein Skript.

**Voraussetzungen** (macOS):

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Node.js 24 für die Web-App: `brew install node` (ohne Web-App nicht nötig)
- optional [LM Studio](https://lmstudio.ai) für den Chat, siehe unten

**Komplett neu aufsetzen:**

```bash
git clone git@github.com:muggabatschr/fussballdb.git
cd fussballdb
scripts/install.sh --launchd
```

`scripts/install.sh` macht der Reihe nach:

1. prüft Docker, uv und npm und startet Docker Desktop, falls es nicht läuft
2. legt `.env` und `web/.env.local` aus den `.env.example`-Dateien an, falls sie fehlen. Leere Werte
   bedeuten Standard, für den Start muss nichts eingetragen werden
3. startet die Datenbank (`docker compose up -d --wait db`, Port 5442)
4. installiert die Python-Abhängigkeiten (`uv sync`)
5. legt die Tabellen an (`fussballdb init-db`)
6. importiert alle Saisons seit 2014/15 (`fussballdb ingest`, ~30 Min.), nur wenn die Datenbank leer ist
7. lädt Kaderwerte, Ausfälle, Quoten, Verletzungshistorie und rechnet alle Prognosen
   (`fussballdb ensure`, beim ersten Mal ~40 Min. für die Verletzungshistorie)
8. lädt fehlende Vereinswappen (`fussballdb logos`)
9. installiert die Web-Abhängigkeiten (`npm install` in `web/`)
10. zeigt am Ende den Datenstand und die nächsten Schritte

| Option | Wirkung |
|---|---|
| `--schnell` | ohne die langsamen Schritte (Verletzungshistorie, Kickbase-Punkte), lassen sich später mit `scripts/update.sh` nachholen |
| `--ohne-web` | ohne `npm install` |
| `--launchd` | tägliches Update um 9:30 einrichten |
| `--mcp` | MCP-Server in Claude Code eintragen (für alle Projekte) |
| `--app` | am Ende API und Web-App in Docker starten |

Das Skript kann jederzeit erneut laufen. Vorhandene `.env`-Dateien und Daten bleiben, es wird nur
ergänzt. Danach:

```bash
docker compose --profile app up -d --build    # Web-App auf http://localhost:3010
```

```bash
uv run fussballdb kickbase-login               # optional, Kickbase (Passwort nur im Terminal)
```

**Von Hand**, falls nötig, sind es dieselben Schritte:

```bash
cp .env.example .env
docker compose up -d --wait db
uv sync
uv run fussballdb init-db
uv run fussballdb ingest      # alle Saisons seit 2014/15, beim ersten Mal ~30 Min. (wird gecacht)
uv run fussballdb ensure      # alles Weitere: Kaderwerte, Ausfälle, Quoten, Prognosen, Verletzungshistorie
uv run fussballdb logos
cd web && cp .env.example .env.local && npm install
```

Die Verletzungshistorie umfasst etwa 1.200 Spielerseiten mit Pausen zwischen den Abrufen und kommt
danach aus dem Cache (`.cache/`, nicht im Git). Später reicht `scripts/update.sh`, siehe
„Daten aktuell halten“.

**Alles löschen und neu anfangen:** `docker compose down -v` entfernt die Container und das
Datenbank-Volume. Danach erneut `scripts/install.sh`.

### Lokales Sprachmodell für den Chat

Eingestellt ist **Qwen 3.8 27B ohne Thinking** (`LOCAL_LLM_MODEL`/`LLM_MODEL=qwen/qwen3.8-27b`,
`LOCAL_LLM_REASONING`/`LLM_REASONING=none`). Im Vergleich mit 10 typischen Fragen (Antwortzeit,
Werkzeugwahl, unbelegte Zahlen, inhaltliche Prüfung jeder Antwort) war Qwen 3.6 35B-A3B ohne Thinking
zwar achtmal schneller (Ø 4 s statt 32 s), machte aber sachliche Fehler (falscher Gegner beim nächsten
Bayern-Spiel, Frage nach Teams über ihren xPts nicht gefiltert). Thinking brachte bei Qwen 3.8 keine
bessere Qualität, kostete aber gut 15 s mehr je Antwort; bei Qwen 3.6 war es zudem unzuverlässig.
Thinking abschalten geht in LM Studio nur über `reasoning_effort: "none"`.

1. [LM Studio](https://lmstudio.ai) installieren (`brew install --cask lm-studio`). Bionic nutzt dieselbe Laufzeit.
2. In LM Studio ein Modell mit Tool-Unterstützung laden, z. B. Qwen3 (27B o. ä., MLX-Variante auf Apple Silicon).
3. Unter Developer den lokalen Server starten (Port 1234), oder per Kommandozeile:
   ```bash
   lms server start
   ```
4. `uv run fussballdb chat`

Mit Ollama statt LM Studio: `LOCAL_LLM_URL=http://localhost:11434/v1` und `LOCAL_LLM_MODEL=<modellname>` in `.env`.
Mit Claude statt lokal: `uv sync --extra claude`, `LLM_PROVIDER=anthropic` und `ANTHROPIC_API_KEY` in `.env`.

## Web-App

Next.js-App in `web/` mit allen Spieltagen aller Saisons (Saison-Dropdown, Blättern), Tabelle inkl.
xG/xPts, Teamseiten (Form, xG-Diagramm, Ausfälle) und Chat.

Jeder Spieltag zeigt Ergebnis, Wahrscheinlichkeiten, den Tipp des Modells und die Kicktipp-Punkte
nach der Punkteregel der Tipprunde samt Bilanz des Spieltags und der Saison:

- **Rückblick-Prognosen** (gespielte Spieltage, `fussballdb backfill`): Modell und Elo sehen nur Spiele
  vor dem ersten Anpfiff des Spieltags, als Ausfälle die damals verletzt gemeldeten Spieler (ab 2023/24).
- **Live-Prognosen** (offene Spiele, `fussballdb predict`): heutiger Datenstand inkl. Verletztenliste.
  Sie werden bis zum Anpfiff bei jedem Update überschrieben und danach eingefroren.
- **Begründung** („Warum 2:1?“ in jeder Kachel, auch im Chat und im MCP): drei bis fünf kurze Punkte,
  direkt aus den Zahlen des Modells erzeugt (`model/explain.py`, kein Sprachmodell): Favorit und erwartete
  Tore mit Elo, Form der letzten Wochen (ab ±5 %), Ausfälle mit ihrem Effekt (ab 3 %), erwartete Punkte
  des Tipps im Vergleich zu den nächstbesten und, falls vorhanden, die Eröffnungsquoten. Im Rückblick
  mit dem damaligen Datenstand.
- **Tipp**: das Ergebnis mit den meisten erwarteten Punkten nach der Punkteregel der Tipprunde
  (`TIPP_PUNKTE` in `.env`, Standard `2,3,4,3` = Sieg 2 Tendenz / 3 Tordifferenz / 4 exakt, Remis 3
  Tendenz / 4 exakt). Remis-Tipps sind trotzdem selten (~1 %): Das Modell erkennt nicht, welche
  ausgeglichenen Spiele remis enden, und ein knapper Sieg-Tipp holt im Mittel mehr Punkte. Daten und Prognosen kommen aus der Python-API (`fussballdb serve`, FastAPI,
Doku unter http://127.0.0.1:8000/docs). Der Chat nutzt das AI SDK mit dem lokalen Modell. Die
Werkzeuge in `web/src/app/api/chat/tools.ts` sind nur dünne Hüllen um die API, die Ergebnisse
erscheinen im Chat als Karten und Tabellen.

**Mit Docker** (Datenbank, API und Web, LM Studio läuft weiter auf dem Mac):

```bash
docker compose --profile app up -d --build
```

Danach http://localhost:3010 öffnen. Beide Ports sind nur lokal erreichbar (`127.0.0.1`). Soll die App
im Netz erreichbar sein, vorher eine Anmeldung davorsetzen.

**Zum Entwickeln**:

```bash
docker compose up -d --wait          # nur die Datenbank
uv run fussballdb serve              # API auf Port 8000
cd web && cp .env.example .env.local && npm install && npm run dev   # Web auf Port 3010
```

`fussballdb ensure` sagt der laufenden API danach, dass sie das Prognosemodell neu laden soll.

**Seiten:**

| Seite | Inhalt |
|---|---|
| `/` | aktueller Spieltag |
| `/spieltag/<saison>/<nr>` | beliebiger Spieltag, Saison-Dropdown und Blättern, Bilanz der Tipps |
| `/tabelle` | Tabelle mit xG, xGA und xPts |
| `/team/<name>` | Form, xG-Verlauf, aktuelle Ausfälle |
| `/chat` | Chat mit dem lokalen Modell |
| `/kickbase` | Kickbase-Prognose, Kauf- und Verkaufskandidaten |

**Wo die Quoten stehen:** in jeder Spieltag-Kachel unter „Warum 2:1?“ als letzte Zeile
(„Buchmacher: 1 … · X … · 2 …“, Wahrscheinlichkeiten aus den Ø-Eröffnungsquoten ohne Marge) und im Chat
unter der Prognosekarte („Markt (Ø-Quoten)“). Für einen Spieltag, den football-data noch nicht
eingestellt hat, fehlt die Zeile. Die Quoten fließen nicht in Prognose oder Tipp ein, sie dienen nur dem
Vergleich.

**Ausfälle in der Kachel:** Namentlich genannt werden nur fehlende Stammspieler (mindestens 50 % der
möglichen Minuten in den letzten 8 Spielen). Eingerechnet werden aber alle Verletzten und Gesperrten mit
ihrem Anteil an xG+xA. Ein Joker wie Karetsas beim BVB (zuletzt 8–76 Minuten) steht deshalb nicht in der
Kachel, senkt die BVB-Torerwartung aber trotzdem (im Beispiel um 2,5 %). Die Prognose im Chat oder MCP
zeigt diesen Anteil als `fehlender_offensivanteil`.

## Kickbase

Eigener Tab „Kickbase“ in der Web-App mit erwarteten Kickbase-Punkten je Spieler für die nächsten 1–5
Spieltage, Marktwert, Marktwert-Trend (7 Tage), Punkten pro Million sowie Kaufkandidaten auf dem
Transfermarkt der eigenen Liga und Verkaufskandidaten im eigenen Kader.

**Zugang** (kostenloses Konto reicht): einmal im Terminal anmelden. E-Mail und Passwort werden nur dort
abgefragt, gespeichert wird nur das Token in `.cache/kickbase.json` (nicht im Git, Dateirechte 600).
Das Token läuft nach etwa einer Woche ab, dann den Befehl wiederholen.

```bash
uv run fussballdb kickbase-login
```

```bash
uv run fussballdb kickbase      # alle Spieler mit Punkte- und Marktwert-Verlauf (beim ersten Mal ~1 Std.)
```

**Erwartete Punkte**: Ein lineares Modell je Position (`features/kickbase_points.py`) erklärt echte
Kickbase-Punkte aus Einsatz, Startelf, Minuten, Toren, Vorlagen, Gegentoren, zu null, Sieg/Remis und
Karten, plus einem geglätteten Spielerwert für alles, was Understat nicht misst (Zweikämpfe, Pässe,
Paraden). Für die Prognose werden die erwarteten Ereignisse eingesetzt: Einsatzchance aus Startelf-Quote,
Aufstellungs-Vorschau, Ausfällen und Kickbase-Status; Tore und Vorlagen aus xG/xA skaliert mit der
Torerwartung gegen den jeweiligen Gegner; Sieg-, Remis- und Zu-null-Chance aus der Spielprognose.
Mit den tatsächlichen Ereignissen erklärt das Modell die Punkte gut (Korrelation 0,93 in 2026/27, der
reine Punkteschnitt 0,43). Wie gut die Prognose vor dem Spiel ist, lässt sich erst nach den nächsten
Spieltagen messen.

**Aktualisierung**: `fussballdb ensure` (täglich per launchd) lädt Marktwerte, Status, Markt und Kader
täglich (schnell) und nach jedem Spieltag die neuen Punkte. Ohne Token wird Kickbase übersprungen; der
API-Container hat das Token nicht und überspringt Kickbase immer.

## Zugriff aus Claude (MCP)

`fussballdb-mcp` ist ein MCP-Server mit den Werkzeugen `naechste_spiele`, `spieltag`, `prognose`,
`team_form`, `direkte_duelle`, `ausfaelle`, `tabelle`, `kickbase`, `sql` und `datenstand`. Damit beantwortet
Claude Fragen direkt auf den eigenen Daten. Es braucht keinen API-Schlüssel: Claude ruft den Server
auf, abgerechnet wird über das Claude-Abo. Die Datenbank muss laufen (`docker compose up -d`).

**Claude Desktop**: in `~/Library/Application Support/Claude/claude_desktop_config.json` ergänzen und
Claude Desktop neu starten:

```json
{
  "mcpServers": {
    "fussballdb": {
      "command": "/Users/hoffmann/.local/bin/uv",
      "args": ["run", "--directory", "/Users/hoffmann/Projekte/privat/fussballdb", "fussballdb-mcp"]
    }
  }
}
```

**Claude Code** (für alle Projekte), alternativ `scripts/install.sh --mcp`:

```bash
claude mcp add fussballdb -s user -- uv run --directory /Users/hoffmann/Projekte/privat/fussballdb fussballdb-mcp
```

Beide Einträge sind auf diesem Mac gesetzt. Neue Werkzeuge erscheinen erst in einer neuen Sitzung bzw.
nach einem Neustart von Claude Desktop.

| Werkzeug | Liefert |
|---|---|
| `naechste_spiele` | kommende Spiele mit Prognose und Tipp |
| `spieltag` | ganzer Spieltag (Saison = Startjahr) mit Tipps, Punkten und Bilanz |
| `prognose` | Wahrscheinlichkeiten, erwartete Tore, wahrscheinlichste Ergebnisse, Tipp, Begründung, Ausfälle |
| `team_form` | letzte Spiele mit xG |
| `direkte_duelle` | frühere Duelle zweier Teams |
| `ausfaelle` | Verletzte und Gesperrte eines Teams |
| `tabelle` | Tabelle mit xG und xPts |
| `kickbase` | erwartete Kickbase-Punkte, Marktwert, Trend, Punkte pro Million; `auswahl` = alle, markt oder kader |
| `sql` | freie Abfrage, nur lesend |
| `datenstand` | wie aktuell die Daten sind, mit Hinweis, wenn eine Quelle noch nichts bereitgestellt hat |

**Skill `/fussball`** (`~/.claude/skills/fussball/SKILL.md`, liegt außerhalb des Projekts): sagt Claude
Code, wie es die Werkzeuge nutzen soll. Zuerst prüft der Skill den Datenstand und wählt dann das
passende Werkzeug. Zahlen übernimmt er nur aus den Werkzeugen und rechnet Ausfälle nicht doppelt ein.
Ein `hint` beim Datenstand gilt als „noch nicht bereitgestellt“, nicht als Fehler. Beispiele:

```
/fussball Wie stehen die Chancen beim nächsten Bayern-Spiel?
/fussball Tipps für den nächsten Spieltag
/fussball Kickbase: wen soll ich kaufen?
```

Der Skill funktioniert nur in Claude Code. Im Chat von Claude Desktop sind die MCP-Werkzeuge trotzdem
da, man fragt einfach normal; die Regeln stehen auch in der Anleitung des Servers. Wer den Skill dort
haben will, lädt die `SKILL.md` als ZIP unter Einstellungen → Fähigkeiten → Skills hoch.

Der Server läuft lokal über stdio. Die Claude-Web- und Mobil-App erreichen ihn so nicht; dafür müsste
er per HTTP (`streamable-http`) und mit Anmeldung im Netz erreichbar sein.

## Befehle

| Befehl | Wirkung |
|---|---|
| `fussballdb init-db` | Tabellen anlegen und Spalten nachziehen (Migrationen) |
| `fussballdb ensure` | Prüfen und nur nötige Schritte ausführen (`--voll`: alle, `--ohne-langsame`: ohne Verletzungshistorie und Kickbase-Punkte) |
| `fussballdb status` | Anzeigen, was aktuell ist und was fehlt |
| `fussballdb update` | Alle schnellen Schritte (wie `ensure --voll --ohne-langsame`) |
| `fussballdb ingest -s 2026` | Einzelne Saison(s) importieren |
| `fussballdb absences` | Verletzte und Sperren neu laden |
| `fussballdb predict -n 2` | Prognosen für die nächsten 2 Spieltage |
| `fussballdb backtest` | Modell rückwirkend gegen Ergebnisse und Wettmarkt testen (`--ausfaelle verletzte/keine/aufstellung`) |
| `fussballdb logos` | Vereinswappen laden (Transfermarkt, ersatzweise OpenLigaDB) nach `web/public/logos` |
| `fussballdb snapshot` | Verletzte und Aufstellungen sichern (täglich per launchd) |
| `fussballdb verletzungshistorie` | Verletzungshistorie aller Spieler seit 2023/24 laden (~30 Min. beim ersten Mal) |
| `fussballdb verletzungen-test` | Ausfälle aus der Verletzungshistorie im Rückblick-Test |
| `fussballdb kickbase-login` | Bei Kickbase anmelden (Passwort nur im Terminal, gespeichert wird das Token) |
| `fussballdb kickbase` | Kickbase-Spieler mit Punkte- und Marktwert-Verlauf, Markt und Kader der Liga laden |
| `fussballdb kaderwerte` | Kaderwerte von Transfermarkt laden (läuft auch in `update`) |
| `fussballdb kaderwert-test` | Kaderwert als Startstärke im Rückblick-Test |
| `fussballdb kalibrierung` | Vorhergesagte gegen eingetretene Häufigkeiten (Heim, Remis, Gast, Über 2,5) |
| `fussballdb tipp-test` | Tipp-Regeln im Rückblick vergleichen |
| `fussballdb kombi-test` | alle Erweiterungen zusammen, jeweils eine weggelassen |
| `fussballdb erweiterungen-test` | Form, Heimvorteil je Team und direkte Duelle im Rückblick-Test |
| `fussballdb xg-varianten` | xG-Varianten (npxG, Spielstand, Rote Karten) im Rückblick-Test vergleichen |
| `fussballdb backfill` | Rückblick-Prognosen für gespielte Spieltage ohne Prognose berechnen (`--force` rechnet alle neu) |
| `fussballdb chat "Wie stehen die Chancen Freiburg gegen Bayern?"` | Frage an das Sprachmodell; ohne Frage interaktiv |
| `fussballdb serve` | REST-API für die Web-App starten |

## Daten aktuell halten

Alles läuft über einen Befehl, der zuerst prüft und dann nur das Nötige lädt:

```bash
scripts/update.sh          # = uv run fussballdb ensure (startet bei Bedarf Docker und die DB)
```

```bash
uv run fussballdb status   # nur anzeigen, was aktuell ist und was fehlt
```

Geprüft werden:

| Schritt | nötig, wenn | frühestens erneut nach |
|---|---|---|
| Ergebnisse, xG, Statistiken | gespielte Spiele ohne Ergebnis, xG oder Schüsse | 3 Std. |
| Kaderwerte | Wert zum 1. des Monats fehlt | 24 Std. |
| Verletzte und Aufstellungen | letzter Schnappschuss älter als 20 Std. | 2 Std. |
| Vorab-Quoten | Spiele der nächsten 7 Tage ohne Quoten | 6 Std. |
| Rückblick-Prognosen | gespielte Spiele ohne Prognose | 6 Std. |
| Kickbase-Marktwerte und Liga | letzter Abruf älter als 20 Std. (nur mit Kickbase-Token) | 6 Std. |
| Live-Prognosen | offene Spiele ohne Prognose, neue Daten oder älter als 24 Std. | 1 Std. |
| Verletzungshistorie (langsam) | noch nie vollständig geladen | 7 Tage |
| Kickbase-Punkte (langsam) | neuer Spieltag ohne Punkte oder Spieler älter als 8 Tage | 12 Std. |

`--voll` erzwingt alle schnellen Schritte; die beiden langsamen laufen auch dann nur, wenn sie nötig sind.

Die Wartezeit verhindert, dass ein Schritt ständig wiederholt wird, wenn eine Quelle noch nicht
nachgezogen hat (Understat-xG, Quoten von football-data).

`fussballdb status` zeigt je Schritt einen Zustand: `aktuell`, `nötig`, `wartet` (nötig, aber die
Wartezeit läuft noch) und `noch nicht da`. Den letzten Zustand gibt es bisher nur bei den Vorab-Quoten.
football-data.co.uk stellt einen Spieltag meist erst 1–2 Tage vor dem ersten Anpfiff in `fixtures.csv`
ein. Bis dahin ist „Quoten für 0 Spiele“ kein Fehler. Status, Update-Ausgabe und das MCP-Werkzeug
`datenstand` (Feld `hint`) melden dann:

```
Vorab-Quoten   noch nicht da   9 Spiele der nächsten 7 Tage ohne Quoten
               Kein Fehler: football-data.co.uk hat die Quoten noch nicht bereitgestellt. Sie kommen
               meist 1–2 Tage vor dem ersten Anpfiff (Fr. 23.10.), voraussichtlich am Mi. 21.10.
               oder Do. 22.10. Das tägliche Update holt sie dann automatisch.
```

Stehen Bundesliga-Spiele in der Datei, die sich keinem Spiel zuordnen lassen, kommt dagegen eine
`[Warnung]`, meist wegen eines neuen Teamnamens in `team_mapping.py`. Bei einem Freitagsspiel kann der
Lauf um 9:30 Uhr zu früh sein. Dann hilft ein `scripts/update.sh` am Freitagnachmittag; für den
Rückblick ist es egal, weil Eröffnungs- und Schlussquoten später aus der Saisondatei kommen. `fussballdb ensure --voll` führt alle Schritte
aus. Jeder Lauf steht in der Tabelle `update_log`. Laufen zwei Updates gleichzeitig an (App und
launchd), wartet das zweite nicht, sondern bricht mit „läuft bereits“ ab.

**Automatisch:**

- **Beim Start der App** (`docker compose --profile app up -d`) prüft die API im Hintergrund und
  aktualisiert bei Bedarf. Die Seiten sind sofort nutzbar; solange das Update läuft, zeigt die Web-App
  oben einen Hinweis und lädt danach neu. Alle Container haben `restart: unless-stopped`, starten also
  nach einem Neustart von Mac oder Docker von selbst und prüfen dabei. Abschalten: `AUTO_UPDATE: "0"`.
- **Täglich um 9:30** per launchd (holt verpasste Läufe nach dem Aufwachen nach). Wichtig für die
  Schnappschüsse von Verletzten und Aufstellungen (Tabelle `lineup_snapshot`, Status `vorschau` oder
  `gespielt`), die später zeigen, was vor dem Anpfiff bekannt war:

```bash
scripts/install.sh --launchd
```

`scripts/de.fussballdb.snapshot.plist` ist eine Vorlage. Das Skript setzt Projekt- und Home-Pfad ein und
legt die Datei unter `~/Library/LaunchAgents/` ab.

Log: `~/Library/Logs/fussballdb-snapshot.log`. Abschalten mit
`launchctl bootout gui/$(id -u)/de.fussballdb.snapshot`.

## Modell

1. **Dixon-Coles** – Angriffs- und Abwehrstärke je Team plus Heimvorteil, angepasst an xG (Understat).
   Startstärke jedes Teams ist sein Kaderwert (Transfermarkt, letzter Stichtag vor dem Spieltag; 2014 bietet
   Transfermarkt nur unregelmäßige Stichtage an, der Import nimmt pro Monat den ersten verfügbaren,
   logarithmiert relativ zur Liga). Mit jedem Spiel übernehmen die Daten mehr; der Effekt zeigt sich
   vor allem an den Spieltagen 1–8. Ältere Spiele zählen weniger (Halbwertszeit etwa 8 Monate).
2. **Elo** mit Tordifferenz-Faktor. 1/X/2 kommt aus einem geordneten Logit.
3. **Ensemble**: 70 % Dixon-Coles, 30 % Elo.
4. **Form**: ein zweites Dixon-Coles nur aus den letzten Wochen (Halbwertszeit 5 Wochen), zu 40 %
   in die Torerwartung gemischt.
5. **Ausfälle**: Verletzte und gesperrte Spieler senken die Torerwartung ihres Teams um ihren halben
   Anteil an xG+xA der letzten 8 Spiele (β = 0,5); fehlende Stamm-Defensivspieler erhöhen die Gegentore
   um 6 %. Verletzte live aus der aktuellen Transfermarkt-Liste, im Rückblick aus der Verletzungshistorie
   zum Stichtag (ab 2023/24). Sperren aus den Karten des letzten Spiels: Rot/Gelb-Rot oder die
   5./10./15. Gelbe der Saison (seit 2014/15). Understat unterscheidet Gelb-Rot und glatt Rot nicht,
   längere Sperren nach glatt Rot sind deshalb nur für das nächste Spiel erfasst.

Backtest 2025/26 und 2026/27 (bis Spieltag 6, 360 Spiele), jeweils nur mit den Daten vor dem Spieltag
(`fussballdb backtest`), Ausfälle aus der Verletztenliste zum Stichtag:

| Modell | RPS | Brier | Log-Loss |
|---|---|---|---|
| Ensemble | 0,1955 | 0,571 | 0,965 |
| Dixon-Coles | 0,1959 | 0,572 | 0,967 |
| Elo | 0,1977 | 0,576 | 0,971 |
| Wettmarkt (Eröffnungsquoten) | 0,1934 | 0,567 | 0,957 |
| Wettmarkt (Schlussquoten) | 0,1930 | 0,566 | 0,956 |
| Raten nach Ø-Verteilung | 0,231 | 0,644 | 1,065 |

Das Modell ist deutlich besser als Raten, aber etwas schlechter als der Wettmarkt (Abstand 0,002).
Mit der echten Aufstellung statt der Verletztenliste (`--ausfaelle aufstellung`, Wissen aus der Zukunft,
nur als Obergrenze) wären es 0,1945. Frühere Fassungen dieser README nannten Backtest-Werte mit
echter Aufstellung und waren dadurch etwas zu optimistisch. Prognosen sind Wahrscheinlichkeiten und
keine Wettempfehlung.

### Was getestet und verworfen wurde

Alle Tests im Rückblick, also pro Spieltag nur mit Daten davor, 2024/25 bis heute (666 Spiele).
Übernommen wird nur, was in mindestens ~90 % der Bootstrap-Ziehungen besser ist. Wiederholbar mit
`fussballdb xg-varianten`, `fussballdb kaderwert-test` und `fussballdb erweiterungen-test`.

| Idee | Änderung RPS | Ergebnis |
|---|---|---|
| Reines xG statt 90 % xG + 10 % Tore | −0,0002 | übernommen (in 97 % der Bootstrap-Ziehungen besser) |
| Kaderwert als Startstärke (k 0,2, Dämpfung 5) | −0,0009, Spieltag 1–8: −0,003 | übernommen (97 % bzw. 99 %); `fussballdb kaderwert-test` |
| Kaderwert stärker gewichtet (k 0,5) | 2026/27: +0,010 | verworfen, Aufsteiger übertreffen ihren Kaderwert |
| Kaderwert nur für Aufsteiger | schlechter | verworfen |
| Formkomponente (40 % Gewicht, Halbwertszeit 5 Wochen) | 2016–26: −0,0002 | übernommen; mit 13 Saisons besser in 91 % der Ziehungen und 7 von 11 Saisons (vorher mit 3 Saisons nur 84 %) |
| Kürzere Halbwertszeit (2–3 statt 8 Monate) | −0,0004 | ähnlich, schwächer belegt (68–75 %); nicht aktiv |
| Heimvorteil je Team | ±0 | verworfen |
| Tor-Skalierung auf echte Tore (xG liegt ~3 % über den Toren) | 2024/25 −0,0014, 2025–26 +0,0005 bis +0,0017 | verworfen; Durchschnitte stimmen danach, Prognosen werden nicht besser |
| Remis-Aufschlag (Poisson unterschätzt Remis um ~2,5 Punkte) | +0,0001 | verworfen; pauschal mehr Remis schadet bei klaren Spielen |
| Tipp nach erwarteten Punkten (Regel der Tipprunde, Remis = 3) | 1,367 statt 1,363 Punkte/Spiel | übernommen; optimiert direkt auf die echte Wertung, ~1 % Remis-Tipps (`fussballdb tipp-test`) |
| Remis-Kalibrierung (Remis bei ausgeglichenen Spielen anheben) | 1,346 Punkte/Spiel, RPS +0,0002 | verworfen; Remis-Quote stimmt danach (24,8 %), aber 12 % Remis-Tipps kosten Punkte |
| Direkte Duelle (Korrektur aus früheren Duellen) | 2024/25 +0,0006, 2025/26 −0,0008 | widersprüchlich, nicht aktiv; mit mehr Duell-Historie erneut testen |
| npxG (ohne Elfmeter), auch mit Ø-Elfmeterwert | +0,0001 | verworfen |
| xG bereinigt auf knappe Spielstände | +0,0005 | verworfen |
| Spiele mit Roter Karte halb gewichtet | ±0 | verworfen (nicht von Zufall unterscheidbar) |
| Ausfälle als „fehlte zuletzt im Kader“ | +0,0007 | verworfen (Rotation und Wechsel verfälschen es) |
| Ausfälle aus der Verletzungshistorie zum Stichtag, β 0,5 | 2023–26: −0,0010 | übernommen; 97 % der Ziehungen, aber stark von 2023/24 getragen (2024/25 schlechter); der erste Test ohne 2023/24 war negativ |
| Kombination aus allen Erweiterungen, jeweils eine weggelassen (`fussballdb kombi-test`) | Form + Verletzte: −0,0005 | Form und Verletzte tragen, Heimvorteil je Team, Duelle und Remis-Kalibrierung nicht |
| Sperren (Rot/Gelb-Rot, 5./10./15. Gelbe) zusätzlich zu den Verletzten | 2016–26: −0,0003 | übernommen; 99 % der Ziehungen, 9 von 11 Saisons, gleichmäßig über alle Jahre |
| Spielerwert über On/Off (xG für/gegen mit und ohne Spieler auf dem Platz) statt xG+xA | 2023–26: +0,0010 | verworfen; zu verrauscht, weil Stammspieler selten fehlen (`features/onoff.py`) |
| Echte Aufstellung (Obergrenze, Wissen aus der Zukunft) | −0,0006 | nur zur Einordnung: Ausfälle sind kaum noch ein Hebel |

## Datenbank

| Tabelle | Inhalt |
|---|---|
| `season`, `team`, `team_alias` | Saisons, Teams, Namen je Quelle |
| `match`, `match_team_stats`, `shot` | Spiele, Statistik je Team (xG, Schüsse, PPDA …), jeder Schuss |
| `odds` | Quoten je Buchmacher, Eröffnung (`is_closing = false`) und Schluss |
| `elo_rating` | Elo je Team und Spiel |
| `player`, `player_match` | Spieler und Einsätze mit Minuten, Toren, Vorlagen, xG, xA, Karten |
| `player_absence` | aktuelle Verletzte von Transfermarkt (`active`), jeder Abruf bleibt erhalten |
| `player_injury` | Verletzungshistorie je Spieler (von–bis, verpasste Spiele) |
| `lineup_snapshot` | voraussichtliche und tatsächliche Aufstellungen (Ligainsider) |
| `squad_value` | Kaderwerte je Team und Stichtag |
| `prediction` | Prognosen (`basis` = live oder rueckblick), Tipp, Ausfälle, Begründung als JSON |
| `update_log` | jeder Update-Schritt mit Grund, Dauer und Ergebnis |
| `kb_player`, `kb_points`, `kb_market_value`, `kb_league_entry` | Kickbase: Spieler, Punkte je Spiel, Marktwert-Verlauf, Markt und Kader der Liga |

Direkt abfragen:

```bash
docker compose exec db psql -U fussball -d fussballdb
```

Neue Teams (Aufsteiger) müssen in `src/fussballdb/ingest/team_mapping.py` eingetragen werden. Der
Import bricht mit einer klaren Meldung ab, wenn ein Name unbekannt ist. Danach `uv run fussballdb logos`
ausführen und die Web-App neu bauen (`docker compose --profile app up -d --build web`), damit das
Wappen erscheint.

## Tests

```bash
uv run pytest                          # Modell, API (braucht laufende DB), lokaler Chat (17 Tests)
cd web && npx tsc --noEmit && npm run lint
```

## Verlauf

Was in welcher Reihenfolge entstanden ist und warum.

1. **Grundlage**: Postgres in Docker, Import aus OpenLigaDB, football-data und Understat, Team-Zuordnung
   über alle Quellen, Dixon-Coles auf xG plus Elo, Backtest gegen den Wettmarkt, Chat mit Werkzeugen.
2. **Lokales Sprachmodell** statt Claude-API: LM Studio mit Qwen, Function Calling über die
   OpenAI-kompatible Schnittstelle. Claude bleibt optional (`--extra claude`).
3. **Web-App** (Next.js) mit API (FastAPI), danach alle Spieltage mit Saison-Dropdown und
   Rückblick-Prognosen, die nur Daten vor dem jeweiligen Spieltag nutzen.
4. **Modell erweitert**, jede Idee einzeln im Rückblick getestet (siehe „Was getestet und verworfen
   wurde“): reines xG, Kaderwert als Startstärke, Form, Verletzte aus der Historie, Sperren. Verworfen
   wurden unter anderem Heimvorteil je Team, direkte Duelle, npxG, Remis-Aufschlag und On/Off.
5. **Mehr Saisons** (seit 2014/15) und mehr Teams in der Zuordnung, Kaderwerte für 1.–3. Liga, damit
   auch Aufsteiger einen Startwert haben.
6. **Tipp nach erwarteten Punkten** mit der Regel der Kicktipp-Runde. Die seltenen Remis-Tipps bleiben
   bewusst so.
7. **Ausfälle**: tägliche Sicherung von Verletztenliste und Aufstellungen, Verletzungshistorie je
   Spieler, Sperren aus Karten, Tore und Vorlagen je Spieler.
8. **Automatisches Update**: `ensure` mit Prüfung je Schritt, `update_log`, Sperre gegen parallele Läufe,
   Start beim Hochfahren der App und täglich per launchd.
9. **Darstellung**: Vereinswappen, kurze Namen ohne Zeilenumbruch, Begründung je Kachel („Warum 2:1?“).
10. **Kickbase**: eigener Tab mit Punkteprognose, Kauf- und Verkaufskandidaten.
11. **MCP-Server** für Claude Desktop und Claude Code, später mit Kickbase-Werkzeug und Skill `/fussball`.
12. **Modellvergleich** für den Chat: Qwen 3.8 27B ohne Thinking gewählt (siehe „Lokales Sprachmodell“).
13. **Hinweis bei fehlenden Vorab-Quoten**: „noch nicht da“ mit erwartetem Termin statt einer Meldung, die
    wie ein Fehler aussieht.
14. **Installationsskript** `scripts/install.sh`, `.env.example` ohne Werte, Repo auf GitHub.

Offen:

- Vergleich mit Qwen 3.6 35B-A3B in 8 Bit, sobald der Download fertig ist
- Prognose für die Champions League (eigener Tab, Spielplan von OpenLigaDB, Ligen über europäische
  Spiele abgeglichen)
