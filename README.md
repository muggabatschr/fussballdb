# fussballdb – Fußball-Prognosen

Datenbank für die 1. Bundesliga mit Ergebnissen und Wettquoten seit 1993/94 und xG, Schüssen, Großchancen,
Kadern und Ausfällen seit 2014/15 (ab dann gibt es xG bei Understat), dazu 2. Bundesliga, DFB-Pokal und Champions
League. Mit Prognosemodell für die nächsten Spiele, Web-App „Fußball-Prognosen“ und einem Chat, in dem ein
Sprachmodell die Daten abfragt und erklärt.

Was es alles gibt:

- **Datenbank** (PostgreSQL in Docker) mit allen Bundesliga-Spielen seit 1993/94, ab 2014/15 mit xG,
  Spielerdaten, Verletzungen, Sperren und Kaderwerten
- **Prognosemodell** mit Wahrscheinlichkeiten, erwarteten Toren und einem Tipp nach der Punkteregel der
  Kicktipp-Runde, für kommende Spiele und im Rückblick mit dem damaligen Datenstand
- **Champions League, 2. Bundesliga, DFB-Pokal**: Prognosen und Tipps aus einem Modell über alle Ligen
- **Tipp-Zettel** zum Kopieren oder als Bild, Erinnerung vor dem Tippschluss als Mac-Mitteilung
- **Spielberichte** zu allen Bundesliga-Spielen ab 2014/15, durchsuchbar im Chat und per MCP
- **Mehrere Kicktipp-Tipprunden**: Tipps und Punkte je Runde nach ihrer Punkteregel, Prognosen für Extratipps
- **Torschützen-Prognose** je Spiel
- **Spiel-Detailseite** mit Form, Direktvergleich, Tabelle, Ausfällen, Aufstellung auf dem Spielfeld mit
  Formation und Noten, Momentum-Graph und Quoten, in den Farben der Teams
- **Stadion, Kapazität und Wetter** je Spiel, so wie am Spieltag, vor dem Spiel mit Kleidungsempfehlung und
  Link zur Anreise mit Bus und Bahn
- **Web-App** mit Spieltagen, Tabelle, Teamseiten, Champions League, Chat und einem Kickbase-Tab
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
| [football-data.co.uk](https://www.football-data.co.uk) | Schüsse, aufs Tor, Ecken, Fouls, Karten, Quoten (B365, Pinnacle, Betfair, Ø, Max; Eröffnung und Schluss), Vorab-Quoten; für 1993/94 bis 2013/14 auch die Ergebnisse (Schüsse ab 2000/01) |
| [OpenLigaDB](https://www.openligadb.de) (`ucl`, `uel`) | Champions League ab 2024/25 und Europa League 2024/25: Spielplan und Ergebnisse |
| Understat, fünf große Ligen | xG der Ligaspiele aus England, Spanien, Italien, Deutschland, Frankreich ab 2022/23 (für das CL-Modell) |
| football-data.co.uk, 18 Ligen | Ligaergebnisse aus England, Spanien, Italien, Deutschland, Frankreich, Niederlande, Portugal, Belgien, Türkei, Schottland, Griechenland, Österreich, Schweiz, Dänemark, Norwegen, Schweden, Polen, Rumänien (für die Europa-Elo) |
| [Understat](https://understat.com) | xG, npxG, xPts, PPDA, Deep, jeder Schuss mit xG, Kader je Spiel mit Minuten/xG/xA |
| [Transfermarkt](https://www.transfermarkt.de) | aktuelle Verletzte und Kranke, Verletzungshistorie je Spieler, Kaderwerte zum 1. jedes Monats |
| [FotMob](https://www.fotmob.com/de/tv-guide/de) | TV-Sender je Bundesliga- und CL-Spiel in Deutschland und Österreich (nächste 7 Tage), xG der Champions-League-Spiele |
| [LiveOnSat](https://liveonsat.com) | Sky-Bundesliga-Kanalnummer je Bundesliga-Spiel (zweite Quelle zu FotMob, gilt für DE und AT) |
| FotMob, Spielseiten | Spielort je Spiel (Stadion, Stadt, Kapazität, Koordinaten) für Bundesliga, 2. Liga, Pokal und CL ab 2026/27 |
| [Open-Meteo](https://open-meteo.com) | Wetter am Stadion zur Spielzeit: Vorhersage bis 16 Tage vorher, danach gemessen (Archiv ERA5) |
| [Ligainsider](https://www.ligainsider.de) | voraussichtliche Aufstellungen vor dem Spiel, tatsächliche danach |
| [Kickbase](https://www.kickbase.com) (inoffizielle API, eigenes Konto) | Punkte, Marktwerte, Status, Markt und Kader der eigenen Liga |

Abgeleitet:
- **Tore und Vorlagen je Spieler** aus den Understat-Kadern (`player_match`)
- **Großchancen** = Schüsse mit xG ≥ 0,3
- **Sperren** = Rot/Gelb-Rot im letzten Spiel oder 5./10./15. Gelbe Karte
- **Elo** je Team und Spiel

Nicht verfügbar: **Ballbesitz**. FBref, Sofascore und FotMob blocken automatisierte Abrufe, die Spalte
`possession` bleibt leer.

**Ältere Saisons 1993/94 bis 2013/14** (`fussballdb historie`, `ingest/history.py`) sind nur zum
Nachschlagen da: Ergebnisse, Halbzeitstand, Statistik und Quoten von football-data, Anstoßzeit und Spieltag
von OpenLigaDB, wo vorhanden (ab 2003/04; davor 15:30 Uhr und Spieltag aus der Spielreihenfolge). Kein xG,
keine Schüsse mit Position, keine Kader. Sie erscheinen im Direktvergleich, in den Spieltagen und Tabellen
früherer Saisons (bis 1994/95 mit zwei Punkten je Sieg), im Chat und über SQL. Das Prognosemodell nutzt
weiter nur Spiele ab 2014/15 (`config.MODEL_FIRST_SEASON`, gefiltert in `model/data.py`); geprüft:
Backtest 2025/26 und alle Modellwerte danach unverändert. Eine Elo mit Vorgeschichte ab 1993 sagt nicht
besser vorher (siehe „Was getestet und verworfen wurde“).

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
2. legt `.env` und `web/.env.local` aus den `.env.example`-Dateien an, falls sie fehlen, und erzeugt dabei
   den Datenbankzugang mit einem Zufallspasswort. Sonst bedeuten leere Werte Standard, für den Start muss
   nichts eingetragen werden
3. startet die Datenbank (`docker compose up -d --wait db`, Port 5442)
4. installiert die Python-Abhängigkeiten (`uv sync`)
5. legt die Tabellen an (`fussballdb init-db`)
6. importiert alle Saisons seit 2014/15 (`fussballdb ingest`, ~30 Min.), nur wenn die Datenbank leer ist,
   und die älteren Saisons ab 1993/94 zum Nachschlagen (`fussballdb historie`, ~1 Min.)
7. lädt Kaderwerte, Ausfälle, Quoten, Verletzungshistorie und rechnet alle Prognosen
   (`fussballdb ensure`, beim ersten Mal ~40 Min. für die Verletzungshistorie)
8. lädt die Daten für die Champions League und rechnet ihre Prognosen (`fussballdb europa`,
   `fussballdb cl-prognosen`, beim ersten Mal ~1 Std. für die Kaderwerte aus 30 Ländern)
9. lädt fehlende Vereinswappen (`fussballdb logos`)
10. installiert die Web-Abhängigkeiten (`npm install` in `web/`)
11. zeigt am Ende den Datenstand und die nächsten Schritte

| Option | Wirkung |
|---|---|
| `--schnell` | ohne die langsamen Schritte (Verletzungshistorie, Kickbase-Punkte, Champions League); später mit `scripts/update.sh` bzw. `fussballdb europa` nachholen |
| `--ohne-web` | ohne `npm install` |
| `--launchd` | tägliches Update um 9:30 und die Tipp-Erinnerung (alle 30 Min.) einrichten |
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
cp .env.example .env          # POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB eintragen (Passwort: openssl rand -hex 24)
docker compose up -d --wait db
uv sync
uv run fussballdb init-db
uv run fussballdb ingest      # alle Saisons seit 2014/15, beim ersten Mal ~30 Min. (wird gecacht)
uv run fussballdb historie    # 1993/94 bis 2013/14, nur zum Nachschlagen (~1 Min.)
uv run fussballdb aufstellungen -s 2025 -s 2024   # optional: Aufstellung und Momentum älterer Saisons ab 2014 (~6 Min. je Saison)
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

Nachtest am 20.10.2026 mit **Qwen 3.6 35B-A3B in 8 Bit** (statt 4 Bit) gegen Qwen 3.8, beide ohne
Thinking, gleiche 10 Fragen, jede Antwort gegen die Daten geprüft. Die 8-Bit-Variante ist rund zehnmal
schneller (Ø 5,5 s statt 57 s) und nennt jetzt den richtigen Gegner. Beim Zusammenfassen erfindet sie
aber weiter Details: falsche Bilanz bei der Leverkusen-Form, ausgedachte Positionen bei den
Gladbach-Ausfällen, verdrehte Bilanz bei den Bayern-Dortmund-Duellen. Qwen 3.8 lag einmal falsch
(Duell-Bilanz) und brach einmal nach zu vielen Abfragen ohne Antwort ab, war sonst aber genau und
ausführlicher. Eingestellt bleibt Qwen 3.8; mit Thinking hing die 8-Bit-Variante zweimal bis zum
Zeitlimit.

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
xG/xPts, Teamseiten (Form, xG-Diagramm in Vereinsfarbe, Ausfälle) und Chat.

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
  Tendenz / 4 exakt; für weitere Tipprunden siehe „Tipprunden“ unter Web-App). Remis-Tipps sind trotzdem selten (~1 %): Das Modell erkennt nicht, welche
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
| `/tabelle` | Tabelle mit xG, xGA und xPts, Platzdifferenz zum Modell, darunter die geschätzte Abschlusstabelle |
| `/team/<name>` | Form, xG-Verlauf, aktuelle Ausfälle; Diagramm und Spieletabelle heben beim Überfahren dasselbe Spiel hervor |
| `/spiel/<id>`, `/cl/spiel/<id>`, `/2bl/spiel/<id>`, `/pokal/spiel/<id>` | Detailseite eines Spiels, per Klick auf die Kachel |
| `/chat` | Chat mit dem lokalen Modell |
| `/cl`, `/cl/<saison>/<runde>` | Champions League: Runde mit Prognosen, Tipps und Bilanz, Saison- und Rundenauswahl |
| `/cl/tabelle`, `/cl/tabelle/<saison>` | Tabelle der CL-Ligaphase mit Platzdifferenz zum Modell, darunter die geschätzte Abschlusstabelle der Ligaphase |
| `/tipps`, `/tipps/<saison>/<nr>` | Tipp-Zettel eines Spieltags: als Text kopieren oder als Bild teilen |
| `/tipprunden` | Kicktipp-Tipprunden verwalten (per Link hinzufügen, Standard setzen, löschen) und Prognosen für ihre Extratipps |
| `/2bl/tipps`, `/cl/tipps`, `/pokal/tipps` (auch `/<saison>/<runde>`) | Tipp-Zettel einer Runde von 2. Liga, CL und Pokal |
| `/2bl`, `/2bl/<saison>/<runde>`, `/2bl/tabelle` | 2. Bundesliga: Spieltage mit Prognosen, Tabelle mit Aufstiegs- und Abstiegschancen |
| `/pokal`, `/pokal/<saison>/<runde>` | DFB-Pokal: Runden mit Prognosen |
| `/kickbase` | Kickbase-Prognose, Aufstellungsvorschlag, Kauf- und Verkaufskandidaten |

**Tabelle:** Neben jedem Platz steht klein, wie viele Plätze ein Team besser (+) oder schlechter (−)
steht, als es die Prognosen vor den bisherigen Spielen erwarten ließen. Dafür zählen je Spiel die erwarteten
Punkte (3 × Siegchance + Remischance) aus der damaligen Prognose. Elversberg mit +10 holt also deutlich
mehr, als das Modell vor den Spielen zugetraut hat. Darunter steht die **geschätzte Abschlusstabelle**
(`model/season_sim.py`): Alle offenen Spiele werden 10.000-mal mit den Wahrscheinlichkeiten der
Live-Prognosen durchgespielt, bei Punktgleichheit entscheidet die erwartete Tordifferenz. Gezeigt werden
erwartete Punkte, der heutige Platz und die Chancen auf Meisterschaft, Platz 1–4 und Abstieg. Beides wird
bei jedem Aufruf neu gerechnet und passt sich damit nach jedem Update an (neue Ergebnisse, xG und
Live-Prognosen). Die Werte stehen auch im Chat und im MCP-Werkzeug `tabelle`.

**Wo die Quoten stehen:** in jeder Spieltag-Kachel unter „Warum 2:1?“ als letzte Zeile
(„Buchmacher: 1 … · X … · 2 …“, Wahrscheinlichkeiten aus den Ø-Eröffnungsquoten ohne Marge) und im Chat
unter der Prognosekarte („Markt (Ø-Quoten)“). Für einen Spieltag, den football-data noch nicht
eingestellt hat, fehlt die Zeile. Die Quoten fließen nicht in Prognose oder Tipp ein, sie dienen nur dem
Vergleich.

**Wettbewerbe:** Über den Spieltagen und Runden lässt sich zwischen Bundesliga, 2. Liga, Pokal und CL
umschalten. „Aktuell“ steht links vor der Saisonauswahl (auf dem Handy vor „Tipp-Zettel“) und
bleibt auf dem aktuellen Spieltag unsichtbar an seinem Platz, damit Auswahl und Pfeile beim Blättern nicht
verrutschen.

**Legenden:** Unter jeder Tabelle und unter den Kacheln stehen die Abkürzungen in einfachen Worten
(`components/Legend.tsx`), jeweils mit Richtung, z. B. „xGA … weniger = besser“ oder „PPDA … weniger = mehr
Pressing“. Kurznamen kommen überall aus `teams.json` bzw. `eu_teams.json` (HSV, Gladbach, Stuttgart II …);
automatisch gebildete Kurznamen werden auf Eindeutigkeit geprüft, sonst steht der volle Name.

**Spiel-Detailseite** (Klick auf eine Spielkachel, in allen vier Wettbewerben; `components/MatchDetail.tsx`,
API `/match/<id>` und `/eu/<comp>/match/<id>`): oben Prognose, Tipp und TV wie in der Kachel, darunter
die Begründung aufgeklappt, die letzten 6 Spiele beider Teams vor dem Spiel (bei CL, 2. Liga und Pokal über
alle Wettbewerbe), der Direktvergleich mit Bilanz und den letzten 10 Duellen, beide Teams in der Tabelle
(CL und 2. Liga mit Zonen-Chancen) und Kaderwert und Elo. Für offene Bundesliga-Spiele kommen die
wahrscheinlichen Torschützen, die voraussichtliche Aufstellung laut Ligainsider und die Ausfälle dazu, für
gespielte die Spielstatistik (Schüsse, Großchancen, Ecken, PPDA, Karten …) und der Vergleich Modell gegen
Quoten. Ausfälle bei CL, 2. Liga und Pokal kommen aus der Transfermarkt-Liste der CL-Teams, sonst aus der
Bundesliga-Liste, wenn ein Bundesligist spielt. Teamnamen, „Warum?“ und „Wer trifft?“ in der Kachel bleiben
einzeln klickbar.

**Aufstellung und Momentum** (`ingest/matchpage.py`, Tabelle `match_page`, `components/Pitch.tsx`,
`components/Momentum.tsx`): von der FotMob-Spielseite, in allen vier Wettbewerben. Die Aufstellung steht auf
einem Spielfeld wie bei FotMob, am Desktop waagerecht (Heim links), auf dem Handy senkrecht: Formation und
Teamnote oben, je Spieler Rückennummer, Note (ab 8 blau, ab 7 grün, ab 6 orange), Spieler des Spiels (★),
Kapitän, Tore, Vorlagen, Karten und Auswechselminute; darunter die Eingewechselten mit Minute und Note, die
übrige Bank und der Trainer. Spielerfotos gibt es bewusst nicht. Vor dem Spiel ist es die voraussichtliche
Aufstellung (etwa zwei Tage vorher), rund eine Stunde vor dem Anpfiff die offizielle; solange es keine
FotMob-Aufstellung gibt, steht die von Ligainsider da. Das Momentum zeigt je Minute, wer Druck gemacht hat
(Balken nach oben Heim, nach unten Gast), mit Toren, Platzverweisen und vergebenen Elfmetern an der Zeitachse.
Gespielte Spiele werden einmal geladen und eingefroren. Die laufende Saison kommt mit dem Update, ältere
Bundesliga-Saisons mit `fussballdb aufstellungen -s 2024` (~1 s je Spiel). Geladen ist die Bundesliga ab
2014/15: Aufstellung und Formation für alle Spiele, Noten und Spieler des Spiels ab 2016/17 (2015/16 nur
vereinzelt), Momentum ab 2023/24 (2022/23 zur Hälfte); davor hat FotMob beides nicht.

**Teamfarben**: Wahrscheinlichkeitsbalken, Direktvergleich, Spielstatistik, Spielfeld und Momentum auf der
Detailseite und das xG-Diagramm der Teamseite (xG in Vereinsfarbe, xGA grau) nutzen die Farben laut FotMob,
für hellen und dunklen Modus getrennt. Je Spiel wählt FotMob sie so, dass sich Heim und Gast unterscheiden;
für Spiele ohne FotMob-Seite gilt die Stammfarbe des Teams (die häufigste Farbe, `matchpage.team_colors`).
Ähneln sich beide Farben zu sehr oder hebt sich eine schlecht vom Hintergrund ab (FotMob gibt im Dunkelmodus
oft beiden Weiß), nimmt ein Team seine Zweitfarbe aus den Farben, die FotMob ihm sonst gibt; und zwar das, bei
dem das Paar den besseren Kontrast zum Layout hat (`matchpage._pick`).
Die S/U/N-Kästchen der Form bleiben grün/grau/orange.

**Tipprunden** (`/tipprunden`, `ingest/kicktipp.py`, `model/tips.py`, Tabelle `tip_round`): Mehrere
Kicktipp-Runden lassen sich per Link hinterlegen; die App liest von der öffentlichen Seite
`kicktipp.de/<runde>/spielregeln` die Punkteregel (Sieg Tendenz/Tordifferenz/exakt, Remis Tendenz),
den Tippschluss und ob es Extratipps gibt. Private Runden zeigen die Regeln nicht öffentlich, Runden mit
anderen Modi (z. B. Punkte nach Quote) werden nicht unterstützt. Unter der Spieltagsauswahl, auf dem
Tipp-Zettel und der Detailseite steht ein Auswahlfeld „Tipprunde“ (gemerkt im Cookie `tipprunde`, gilt für
die ganze App). Tipps, Begründung („… bringt im Schnitt …“), Tipp-Punkte und Bilanz richten sich dann nach
ihrer Regel. Dafür speichert jede Prognose die Wahrscheinlichkeit jedes Ergebnisses 0:0 bis 9:9
(`prediction.score_probs`); daraus folgt für jede Regel der Tipp mit den meisten erwarteten Punkten, ohne das
Modell neu zu rechnen. Für die Standardregel bleiben die gespeicherten Tipps unverändert (geprüft: aus
`score_probs` ergibt sich bei allen 3.969 Prognosen derselbe Tipp). Ältere Prognosen bekamen `score_probs`
einmal mit `fill_score_probs` nachgetragen, ausgerichtet an ihren gespeicherten 1/X/2-Werten. Die Regeln der
beiden Runden 2026/27 liegen nah beieinander, die Tipps unterscheiden sich nur bei wenigen ausgeglichenen
Spielen (2 von 252 offenen); die Punkte zählen aber unterschiedlich (2025/26 rückblickend 421 bzw. 273).
Für Runden mit Extratipps (Bonusfragen) zeigt `/tipprunden` die Fragen von
`kicktipp.de/<runde>/tippuebersicht?bonus=true` mit den wahrscheinlichsten Antworten (`model/bonus.py`).
Weil Extratipps vor dem 1. Spieltag abgegeben werden, gilt als Prognose der Wissensstand zum Tippschluss der
Frage: Modell nur mit Spielen, Kaderwerten und gemeldeten Verletzten bis dahin, alle Saisonspiele damit
vorhergesagt und die Saison 10.000-mal von vorn durchgespielt. Daneben steht der Stand heute (aus den
Live-Prognosen), bei entschiedenen Fragen die Antwort. Erkannt werden Meister, Herbstmeister (bis zum
17. Spieltag), Plätze 16–18, Abstieg und Platz 1–4. Der erste Trainerwechsel ist eine Näherung, weil es
keine Trainerdaten gibt: wer nach dem 8. Spieltag am wahrscheinlichsten auf Platz 16–18 steht (2026/27 hätte
sie Gladbach nicht vorhergesehen). Für das Team des Torschützenkönigs (`top_scorer`) bekommt jeder Spieler
seine Tore bis zum Stichtag plus erwartete Tore in jedem übrigen Spiel: Torrate je zur Hälfte aus xG und echten
Toren pro 90 Minuten (zum Positionsschnitt geglättet, weil Torjäger dauerhaft öfter treffen als ihr xG), mal
erwartete Minuten (Startelf- und Einwechselquote ab seinem ersten Spiel für den Verein), skaliert mit der
Torerwartung seines Teams gegen den jeweiligen Gegner. Die Saison wird 10.000-mal ausgespielt, je Durchlauf
streut die Torrate um rund ±35 % (Verletzung, Form, Rotation). Zum Tippschluss 2026/27: Kane rund 31
erwartete Tore, Bayern 37 %. Grenze: Zum Tippschluss kennt das Modell keine Neuzugänge, die noch nicht in der
Bundesliga gespielt hatten, und ordnet Wechsel innerhalb der Liga dem alten Verein zu.

**Spielberichte** (`reports.py`, Tabelle `match_report`): Zu jedem Bundesliga-Spiel ab 2014/15 gibt es einen
Bericht im Stil einer Sportzeitung, gebaut aus unseren Daten statt von einem Sprachmodell geschrieben (schnell,
rückwirkend für alle 3.726 Spiele in Sekunden, ohne erfundene Details). Schlagzeile („Muheim erlöst Hamburg spät“,
„Bochum gewinnt das Revierderby“), Ortszeile mit Datum, Spieltag, Stadion, Wetter (ab 2026/27) und Ergebnis, dann
der Einstieg im Perfekt („Im Kellerduell hat Hoffenheim am Sonntagnachmittag bei Gladbach mit 2:1 die Oberhand
behalten“). Der Spielverlauf steht in zwei Absätzen, je Halbzeit: wer das Spiel bestimmte, jedes Tor mit Minute,
Schütze, Vorlage und Art (Elfmeter, Kopfball, Ecke, Nachschuss, Joker), Pfosten, verschossene Elfmeter und die
größte vergebene Chance je Team. Der letzte Absatz ordnet ein: Doppelpack und Saisontore des Schützen, verdient
oder glücklich nach den Chancen, Überraschung, Folgen für die Tabelle (Tabellenführung, Abstiegszone, „vorerst“,
wenn der Spieltag noch läuft), Serien („der dritte Sieg in Folge“, „seit sieben Spielen ohne Sieg“) und Ausfälle.
Derbys, Spitzenspiele (beide unter den ersten drei) und Kellerduelle (beide ab Platz 15) werden als solche
benannt. Mit der FotMob-Aufstellung nennt der Bericht die Formationen (ab 2014/15) und den Spieler des Spiels
mit Note (ab 2016/17). Danach folgt die Zeile „Zahlen zum Spiel“. Die Formulierungen wechseln von Spiel zu Spiel, bleiben für
ein Spiel aber gleich. Dazu eine Zeile
**Stichworte** zum Verlauf, je Team zugeordnet („Comeback von Gladbach“, „spätes Siegtor von HSV“,
„glücklicher Sieg von …“, Platzverweis, Elfmeter, Eigentor, Überraschung …). Die Berichte stehen auf der
Detailseite gespielter Spiele.
Suche (`/reports/search`, im Chat `search_reports`, im MCP `spielberichte`): Volltextsuche auf Deutsch
(Postgres) und Vektorsuche (pgvector, Embeddings von `nomic-embed-text` aus LM Studio), die Ränge werden mit
Reciprocal Rank Fusion kombiniert; die Vektorsuche zählt halb, weil die gleich aufgebauten Berichte ihr wenig
Unterschied bieten. Mit Teamfilter gewinnen Berichte, deren Stichworte das gesuchte Ereignis diesem Team
zuschreiben. „neueste zuerst“ liefert für Fragen wie „wann zuletzt …“ die jüngsten Treffer. Ohne LM Studio
läuft die Volltextsuche allein. Das Sprachmodell im Chat fasst die gefundenen Berichte zusammen; für Zählfragen
ist das SQL-Werkzeug genauer. Der API-Container erreicht LM Studio über `DOCKER_LLM_URL` (Standard
`http://host.docker.internal:1234/v1`), weil `localhost` im Container der Container selbst ist.

**Reihenfolge wie bei Kicktipp:** Spieltag, Tipp-Zettel, Chat und Erinnerung zeigen die Bundesliga-Spiele in
der Reihenfolge von Kicktipp (innerhalb einer Anstoßzeit folgt sie keiner erkennbaren Regel). Das Update liest
sie vom öffentlichen Spielplan einer Tipprunde (`kicktipp.de/<runde>/tippspielplan?spieltagIndex=<nr>`,
`ingest_order`), alle Bundesliga-Runden haben denselben. Gespeichert als `match.kicktipp_pos`; ohne Tipprunde
mit öffentlichem Spielplan oder bei älteren Saisons wird nach Anstoß sortiert. Neu gelesen werden fehlende
Spieltage und die nächsten drei offenen, weil Kicktipp neu sortiert, wenn sich Anstoßzeiten verschieben. Gelesen werden nur diese
beiden öffentlichen Seiten, ohne Anmeldung; Kicktipp hat keine offizielle Schnittstelle. Die Tipp-Zettel
und Tabellen von CL, 2. Liga und Pokal nutzen weiter die Standardregel.

**Tipp-Zettel** (`/tipps`, Link „Tipp-Zettel“ neben der Spieltags- bzw. Rundenauswahl, für Bundesliga,
2. Liga, CL und Pokal): alle Tipps eines Spieltags oder einer Runde untereinander. „Als Text“ kopiert sie zum Einfügen, „Als Bild“ zeichnet ein PNG mit Wappen; auf dem Handy
öffnet sich das Teilen-Menü (z. B. Messenger), am Rechner wird es heruntergeladen. Fragt man im Chat nach dem
Tipp-Zettel, erscheint dieselbe Box mit „Als Bild“ und „Als Text“ (Werkzeug `get_tip_sheet`, für alle vier
Wettbewerbe).

**Erinnerung vor dem Tippschluss** (`fussballdb erinnerung`, `reminder.py`): Beginnt der nächste
Bundesliga-Spieltag in weniger als 3 Stunden, kommt einmal eine Mac-Mitteilung mit allen Tipps. Fehlt ein
Spieler aus dem eigenen Kickbase-Kader (verletzt laut Kickbase oder Transfermarkt), kommt eine zweite.
Läuft alle 30 Minuten per launchd (`scripts/de.fussballdb.erinnerung.plist`, eingerichtet mit
`scripts/install.sh --launchd`); ohne laufende Datenbank passiert nichts. Ausprobieren:
`uv run fussballdb erinnerung --test`.

**Wer trifft?** (aufklappbar in jeder offenen Bundesliga-Kachel, auch im Chat, `features/scorers.py`): die
drei wahrscheinlichsten Torschützen je Team mit der Chance auf mindestens ein Tor. Grundlage sind xG pro
90 Minuten (über 300 Tage, zum Positionsschnitt geglättet), die erwarteten Minuten aus Startelf-Quote,
voraussichtlicher Aufstellung und Ausfällen sowie die Torerwartung des Teams gegen diesen Gegner;
P = 1 − e^(−erwartete Tore). Die Startelf-Chance kommt aus Ligainsider und der FotMob-Aufstellung zusammen
(`start_chance` in `features/kickbase_projection.py`): sehen beide einen Spieler nicht in der Elf, sinkt sie auf
15 %, steht er bei beiden drin, liegt sie bei 92 %; die offizielle FotMob-Aufstellung etwa eine Stunde vor dem
Anpfiff gilt allein. Nicht im Rückblick getestet. Bei Topstürmern liegt der Wert eher niedrig, weil
die Glättung sie zum Positionsschnitt zieht (Kane gegen Freiburg 39 %).

**xG in der Kachel:** Bei gespielten Bundesliga-Spielen steht unter dem Ergebnis das xG und unter jedem Team
die Differenz Tore minus xG: grün = mehr Tore als die Chancen hergaben (überperformt), orange = weniger
(unterperformt), grau = weniger als ein halbes Tor Abweichung. Das gilt auch für die Champions League;
deren xG kommen von FotMob (`ingest/cl_xg.py`, seit 2024/25, nach jedem Spieltag nachgeladen).

**Stadion und Wetter** (Kachel und Detailseite, `ingest/venues.py`, `ingest/weather.py`,
`components/VenueLine.tsx`): Stadion mit Kapazität laut FotMob-Spielseite, darunter das Wetter in der Stunde
nach dem Anpfiff (Temperatur, Wetterlage, Regenwahrscheinlichkeit bzw. gemessener Regen, Wind). Offene Spiele
der nächsten 14 Tage bekommen ihren Spielort täglich neu, gespielte einmal danach; dann wird er eingefroren.
So bleiben Name und Kapazität, wie sie am Spieltag waren, auch wenn das Stadion später umbenannt oder
umgebaut wird. FotMob kennt auch Ausweichstadien (Schachtar 2024/25 in Gelsenkirchen). Das Wetter ist vor
dem Spiel die Vorhersage von Open-Meteo (alle 6 Std. neu), drei Stunden nach dem Anpfiff der gemessene Wert
(eingefroren). Vor dem Spiel steht darunter eine **Kleidungsempfehlung** für Zuschauer
(`clothingAdvice` in `web/src/lib/weather.ts`): Schichten nach gefühlter Temperatur (Windchill unter 10 °C,
2 °C Abzug für 90 Minuten im Stadion; unter 0 °C dicke Winterjacke mit Mütze, Schal, Handschuhen, bis 5 °C
Winterjacke, bis 10 °C warme Jacke, bis 15 °C Übergangsjacke, bis 20 °C Pullover), ab 40 %
Regenwahrscheinlichkeit Regenjacke oder Poncho (Schirme sind in den meisten Stadien verboten), bei Wind ab
30 km/h etwas Winddichtes, ab 25 °C und Sonne Kappe und Sonnencreme.

**Anreise mit Bus und Bahn** (offene Spiele, `route` in `ingest/venues.py`, `components/RouteLink.tsx`, im MCP
das Werkzeug `anreise`): Link zu Google Maps mit öffentlichen Verkehrsmitteln und „Ankunft bis“ eine Stunde
vor dem Anpfiff, in Ortszeit am Stadion (CL-Spiele im Ausland umgerechnet). Beim Klick fragt die Seite zuerst
im selben Tab den Standort ab und öffnet danach Google Maps mit den Koordinaten als Start (ein vorher
geöffnetes Tab würde die Nachfrage des Browsers verdecken). Ohne Standort (abgelehnt, keine Antwort nach
10 Sekunden, Seite nicht über https oder localhost, z. B. über die IP im Heimnetz) und bei „Link in neuem Tab
öffnen“ kommt der offizielle Link ohne Uhrzeit; dort setzt Google den aktuellen Standort selbst ein. Es
braucht keinen API-Schlüssel. Die Uhrzeit steht im Format `data=!4m6!4m5!2m3!6e1!7e2!8j<Zeit>!3e3`,
das Google selbst für seine Links nutzt, das aber nicht offiziell dokumentiert ist; `url_ohne_zeit` ist der
dokumentierte Rückfall (`api=1`, `travelmode=transit`). Die Verkehrsverbünde direkt anzusprechen geht nicht
einheitlich (jeder Verbund hat ein eigenes Linkformat, bahn.de seit 2024 keine dokumentierten Parameter).

Stadion und Wetter gibt es ab 2026/27; ältere Spiele haben keinen Spielort, weil frei verfügbare Daten die
Sponsorennamen der Stadien nicht mit Zeitraum führen (Wikidata kennt z. B. nur „Signal Iduna Park“).

**TV-Sender in der Kachel:** Bei offenen Spielen steht unten je eine Zeile für Deutschland und Österreich
mit den Logos der genauen Kanäle, z. B. Sky Sport Bundesliga 5 und WOW, in der CL DAZN oder Prime Video
und in Österreich Sky Sport Austria mit Kanalnummer. Laufen in beiden Ländern dieselben Kanäle (Sky Bundesliga 1 in DE
und Sky Sport Bundesliga 1 in AT gelten als gleich), steht nur eine Zeile „DE/AT“ da. Quelle ist das TV-Programm von FotMob für beide
Länder (`ingest/tv.py`), täglich geladen und über Anstoßzeit und Teamnamen zugeordnet. Weggelassen werden
Zugänge und Kopien (Sky Go, Sky Stream, Sky X, UHD, Showcase) und, sobald ein nummerierter Kanal da ist,
der allgemeine Sky-Bundesliga-Kanal und Top Event. Sky Österreich zeigt die Bundesliga auf denselben
Sky-Bundesliga-Kanälen wie Sky Deutschland, die Kanalnummer ist also in beiden Ländern gleich. FotMob gibt
für Deutschland aber oft eine falsche Nummer an (Leipzig – Elversberg 2026/27: DE 2, AT 4, richtig 4).
Deshalb liest `ingest/tv.py` für die Bundesliga zusätzlich [LiveOnSat](https://liveonsat.com) (gespeichert
als Land `LS`); dessen Nummer gilt für DE und AT, ohne LiveOnSat die österreichische von FotMob
(`align_sky_numbers`, nur in der Anzeige, die Rohdaten bleiben). Fällt LiveOnSat aus, läuft das Update mit
FotMob allein weiter. Steht ein Sender noch nicht fest, heißt es „noch
offen“. FotMob kennt die Kanäle etwa eine Woche im Voraus; bei gespielten Spielen wird die Zeile
ausgeblendet.

Die Logos liegen unter `web/public/tv/` (Sky-Kanäle von sky.de, DAZN von FotMob, WOW von wowtv.de, Prime
Video von Wikimedia Commons); die Zuordnung Kanalname → Logo steht in `web/src/lib/tv.ts`. Sender ohne
Logo (z. B. RTL, Sat.1, ServusTV) erscheinen als kurzer Text. Die Sky-Logos sind für hellen Hintergrund
gemacht und stehen deshalb auf einem weißen Schild. Ausgeliefert werden sie unverändert in
Originalgröße (`unoptimized`), sonst verkleinert Next.js sie und sie wirken unscharf.

**Ausfälle in der Kachel:** Namentlich genannt werden nur fehlende Stammspieler (mindestens 50 % der
möglichen Minuten in den letzten 8 Spielen). Eingerechnet werden aber alle Verletzten und Gesperrten mit
ihrem Anteil an xG+xA. Ein Joker wie Karetsas beim BVB (zuletzt 8–76 Minuten) steht deshalb nicht in der
Kachel, senkt die BVB-Torerwartung aber trotzdem (im Beispiel um 2,5 %). Die Prognose im Chat oder MCP
zeigt diesen Anteil als `fehlender_offensivanteil`.

## Kickbase

Eigener Tab „Kickbase“ in der Web-App mit erwarteten Kickbase-Punkten je Spieler für die nächsten 1–5
Spieltage, Marktwert, Marktwert-Trend (7 Tage), Punkten pro Million sowie Kaufkandidaten auf dem
Transfermarkt der eigenen Liga und Verkaufskandidaten im eigenen Kader.

**Zugang** (kostenloses Konto reicht): oben im Kickbase-Tab E-Mail und Passwort eingeben und auf
„Anmelden“ klicken. Beides geht nur einmal an Kickbase und wird nirgends gespeichert oder protokolliert;
gespeichert wird nur das zurückgegebene Token, in der Tabelle `kb_session`. So nutzen Web-App (auch in
Docker) und Terminal dieselbe Anmeldung. Danach lädt die App Kader, Markt und Marktwerte im Hintergrund.
Ist man in mehreren Ligen, lässt sich die Liga dort wählen; gespeichert werden dann nur Markt und Kader der
gewählten Liga, die der vorherigen werden beim Wechsel entfernt. „Abmelden“ löscht das Token. Das Token läuft
nach etwa einer Woche ab, dann erscheint das Formular wieder. Im Terminal geht es weiterhin mit:

```bash
uv run fussballdb kickbase-login
```

```bash
uv run fussballdb kickbase      # alle Spieler mit Punkte- und Marktwert-Verlauf (beim ersten Mal ~1 Std.)
```

Die Datenbank ist nur vom eigenen Rechner aus erreichbar (`127.0.0.1:5442`), weil sie das Token enthält.

**Aufstellung** (oben im Kickbase-Tab, `features/kickbase_lineup.py`): die Elf mit den meisten erwarteten
Punkten am nächsten Spieltag aus dem eigenen Kader, über alle Kickbase-Formationen (3-4-3 bis 5-4-1, immer
ein Torwart). Verletzte oder gesperrte eigene Spieler stehen rot darüber und spielen nicht mit.

**Erwartete Punkte**: Ein lineares Modell je Position (`features/kickbase_points.py`) erklärt echte
Kickbase-Punkte aus Einsatz, Startelf, Minuten, Toren, Vorlagen, Gegentoren, zu null, Sieg/Remis und
Karten, plus einem geglätteten Spielerwert für alles, was Understat nicht misst (Zweikämpfe, Pässe,
Paraden). Für die Prognose werden die erwarteten Ereignisse eingesetzt: Einsatzchance aus Startelf-Quote,
Aufstellungs-Vorschau (Ligainsider und FotMob), Ausfällen und Kickbase-Status; Tore und Vorlagen aus xG/xA skaliert mit der
Torerwartung gegen den jeweiligen Gegner; Sieg-, Remis- und Zu-null-Chance aus der Spielprognose.
Mit den tatsächlichen Ereignissen erklärt das Modell die Punkte gut (Korrelation 0,93 in 2026/27, der
reine Punkteschnitt 0,43). Wie gut die Prognose vor dem Spiel ist, lässt sich erst nach den nächsten
Spieltagen messen.

**Aktualisierung**: `fussballdb ensure` (täglich per launchd) lädt Marktwerte, Status, Markt und Kader
täglich (schnell) und nach jedem Spieltag die neuen Punkte. Ohne Anmeldung wird Kickbase übersprungen.

## Champions League

Eigener Tab „CL“ mit allen Runden seit 2024/25 (Ligaphase, Play-offs, Achtelfinale bis Finale), gleich
aufgebaut wie die Bundesliga-Spieltage: Wahrscheinlichkeiten, erwartete Tore, Tipp nach der Punkteregel,
Begründung und Bilanz. Gespielte Runden zeigen die Rückblick-Prognose (nur Daten bis zum ersten Anpfiff
der Runde), offene die Live-Prognose.

**Warum anders als in der Bundesliga:** Für viele Ligen gibt es kein xG, keine Kader und keine Ausfälle,
und Teams aus verschiedenen Ländern spielen selten gegeneinander. Die Prognose stützt sich deshalb auf:

1. **xG-Modell** (70 %): Dixon-Coles wie in der Bundesliga über alle Liga- und Europapokalspiele seit
   2022/23. Zielgröße ist xG, wo vorhanden (fünf große Ligen von Understat, Champions League von FotMob),
   sonst Tore. Startstärke aus dem Kaderwert relativ zum europäischen Mittel (k = 0,25), dazu eine
   Formkomponente (40 %, Halbwertszeit 5 Wochen). Die Ligen werden über die Europapokalspiele und den
   Kaderwert verbunden.
2. **Europaweite Elo** (30 %) über gut 22.000 Ligaspiele aus 18 Ländern (football-data) und alle
   Europapokalspiele. Ein Team startet bei seinem ersten Spiel mit einer Elo aus seinem Kaderwert
   (Transfermarkt: 1500 bei 50 Mio. €, +104 je Verdopplung). Zu jeder neuen Saison rückt die Elo ein
   Drittel Richtung Kaderwert (Transfers im Sommer). K-Faktor 20 in der Liga, 30 im Europapokal,
   Heimvorteil 65 Punkte, Siege mit 2 Toren zählen 1,5-fach, höhere mehr. Daraus erwartete Tore über ein
   Poisson-Modell mit Elo-Differenz und Heimvorteil (im Finale keiner).
3. **Tipp** wie in der Bundesliga: das Ergebnis mit den meisten erwarteten Punkten.

Teams aus Ländern ohne football-data-Liga (Tschechien, Kroatien, Serbien, Ukraine, Slowakei, Zypern,
Aserbaidschan, Kasachstan, Bulgarien, Ungarn, Israel, Lettland) haben nur ihren Kaderwert und ihre
Europapokalspiele. Absteiger fehlen auf den Transfermarkt-Ligaseiten, sie starten im unteren Viertel ihrer
Liga (betrifft unter den CL-Teams nur Girona 2024/25).

**xG-Modell gegen Elo** (`fussballdb cl-xg-test`, Oktober 2026, 423 Spiele, jede Runde nur mit dem Stand
vor ihrem ersten Anpfiff):

| Variante | 2024/25 | 2025/26 | 2026/27 (45 Spiele) | gesamt |
|---|---|---|---|---|
| Elo allein (bis Oktober 2026) | 0,1958 | 0,2020 | 0,1697 | 0,1958 |
| **xG/Elo 70/30 + Form (übernommen)** | 0,1910 | 0,1997 | 0,1764 | 0,1934 |
| xG/Elo 50/50 + Form | 0,1919 | 0,2000 | 0,1742 | 0,1936 |
| xG allein | 0,1935 | 0,1995 | 0,1790 | 0,1946 |
| Tore statt xG, 70/30 + Form | 0,1925 | 0,1993 | 0,1778 | 0,1940 |

Die Variante wurde vorab an 2024/25 gewählt. Über alle Spiele ist sie in 91 % der Bootstrap-Ziehungen
besser als die Elo allein, in 2024/25 und 2025/26 deutlich, in den ersten 45 Spielen 2026/27 schlechter.
Im strengen Test nur ab 2025/26 sind es 58 %, deshalb wird nach der Ligaphase 2026/27 erneut geprüft.
Ein Großteil des Gewinns kommt aus Struktur und Form, Tore statt xG sind fast gleich gut.

**Erster Rückblick-Test der Elo** (`fussballdb cl-test`, Stand vor der Umstellung):

| Saison | Spiele | RPS Modell | Elo + Kaderwert-Merkmal | nur Kaderwert | Grundverteilung | Punkte je Spiel |
|---|---|---|---|---|---|---|
| 2024/25 | 189 | 0,1958 | 0,1967 | 0,2037 | 0,2416 | 1,49 |
| 2025/26 | 189 | 0,2020 | 0,2016 | 0,2041 | 0,2326 | 1,37 |
| 2026/27 (bis 2. Spieltag) | 36 | 0,1796 | 0,1812 | 0,1901 | 0,2361 | 1,69 |
| gesamt | 414 | 0,1972 | 0,1975 | 0,2027 | 0,2370 | 1,45 |

In der Ligaphase ist das Modell deutlich treffsicherer (RPS 0,192, 1,50 Punkte je Spiel) als in der
K.-o.-Phase (0,217, 1,29), wo ausgeglichene Teams aufeinandertreffen. Einen Vergleich mit dem Wettmarkt
gibt es nicht: Kostenlose Quellen haben keine Champions-League-Quoten. Verworfen:

- **Kaderwert-Verhältnis als zusätzliches Merkmal** im Tormodell: nicht besser als die Elo allein (nur
  29 % der Bootstrap-Ziehungen), er steckt schon im Startwert und im Saison-Rückzug.
- **Abgestimmte Elo-Parameter** (Kaderwert-Gewicht, K-Faktoren, Saison-Rückzug, Heimvorteil): Was an
  2024/25 am besten passte, war an 2025/26 und 2026/27 schlechter (RPS 0,2002 statt 0,1977, gemessen
  noch mit Kaderwert-Merkmal). Die
  Unterschiede sind Rauschen, es bleiben die Startwerte.

Das Modell sagt im Schnitt 22 % Remis voraus, in der CL endeten seit 2024/25 aber nur 16 % der Spiele
remis. Remis-Tipps gibt es deshalb keine. Bei K.-o.-Spielen zählt das Endergebnis von OpenLigaDB, also
inklusive Verlängerung, ohne Elfmeterschießen.

**Tabelle der Ligaphase** (`/cl/tabelle`, `model/cl_table.py`): wie in der Bundesliga mit der Zahl neben
dem Platz, wie viele Plätze ein Team besser (+) oder schlechter (−) steht, als es die Prognosen vor den
gespielten Spielen erwarten ließen. Darunter die geschätzte Abschlusstabelle der Ligaphase aus 10.000
Simulationen der offenen Spiele, mit den Chancen auf Platz 1–8 (direkt ins Achtelfinale), 9–24
(Play-offs) und das Ausscheiden. Bei Punktgleichheit entscheiden erwartete Tordifferenz und Tore. Auch im
MCP-Werkzeug `cl_tabelle`.

**Ausfälle in der CL** (`ingest/cl_absences.py`): Verletzte und Gesperrte aller Teams mit CL-Spielen in den
nächsten 14 Tagen von Transfermarkt (Vereinsseite „Sperren und Verletzungen“), täglich geladen. Ihr Gewicht
wird über den Anteil am Kaderwert geschätzt. Sie stehen in der Begründung („Es fehlen bei …, zusammen
18 % des Kaderwerts, nicht eingerechnet“), fließen aber noch nicht in die Prognose ein: Es gibt keine
Historie, mit der sich das testen ließe. Nach einigen Spieltagen lässt sich das nachholen.

**Einrichten** (einmalig ~1 Std., vor allem Kaderwerte von 30 Ligen zu 19 Stichtagen):

```bash
uv run fussballdb europa
```

```bash
uv run fussballdb cl-prognosen
```

Danach hält `fussballdb ensure` alles aktuell (Schritt „Champions League“). Für eine neue Saison muss
das OpenLigaDB-Kürzel in `ingest/europe.py` (`EURO_COMPETITIONS`) ergänzt werden, neue Teilnehmer aus
kleinen Ländern unter `CLUBS` und `OLDB_NAMES`. Der Import bricht bei unbekannten Namen mit einer klaren
Meldung ab.

## 2. Bundesliga und DFB-Pokal

Beide laufen über dasselbe Modell wie die Champions League (`model/europe.py`): Ligaspiele von OpenLigaDB
(2. und 3. Liga seit 2022/23, DFB-Pokal seit 2024/25) kommen zu den europäischen Ligen dazu, Kaderwerte von
Transfermarkt (L2, L3). Frühere Bundesligisten bleiben dasselbe Team über alle Ligen; Amateure im Pokal
ohne Liga- und Kaderdaten starten deutlich schwächer (Elo 400 unter dem Basiswert, im Dixon-Coles
Angriff −0,6 / Abwehr +0,6). Für die 2. Liga gibt es kein xG, ihr Dixon-Coles rechnet mit Toren.

Rückblick-Test (`fussballdb cl-xg-test` mit `competition`, eingestellt an 2024/25):

| | Elo | Dixon-Coles allein | xG/Elo 70/30 + Form | übernommen |
|---|---|---|---|---|
| 2. Bundesliga (1.296 Spiele) | 0,2234 | 0,2235 | 0,2231 | Elo: im Einstelljahr am besten, Mischungen danach kaum besser (87 %) |
| DFB-Pokal (158 Spiele) | 0,1708 | **0,1420** | 0,1483 | Dixon-Coles allein: in allen Saisons besser, 99 % der Ziehungen |

Seiten: `/2bl` (Spieltage), `/2bl/tabelle` (Tabelle mit Modell-Platz und Hochrechnung: Aufstieg,
Relegation, Abstieg), `/pokal` (Runden). MCP: `wettbewerb` (D2, DFB oder CL) und `tabelle_2_liga`.
Eingerichtet wird alles mit `uv run fussballdb europa` und `uv run fussballdb cl-prognosen`.

## Zugriff aus Claude (MCP)

`fussballdb-mcp` ist ein MCP-Server mit den Werkzeugen `naechste_spiele`, `spieltag`, `prognose`,
`team_form`, `direkte_duelle`, `ausfaelle`, `tabelle`, `kickbase`, `champions_league`, `wettbewerb`,
`tabelle_2_liga`, `cl_tabelle`, `anreise`, `tipprunden`, `spielberichte`, `sql` und `datenstand`. Damit beantwortet
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
| `spieltag` | ganzer Spieltag (Saison = Startjahr) mit Tipps, Punkten und Bilanz; `tipprunde` = Tipps und Punkte nach der Regel dieser Kicktipp-Runde |
| `spielberichte` | Spielberichte durchsuchen (Frage, Team, Saison, `neueste_zuerst`) für Verläufe und Zusammenfassungen |
| `tipprunden` | hinterlegte Kicktipp-Runden mit Punkteregel; mit `runde` die Extratipps mit Prognose |
| `prognose` | Wahrscheinlichkeiten, erwartete Tore, wahrscheinlichste Ergebnisse, Tipp, Begründung, Ausfälle |
| `team_form` | letzte Spiele mit xG |
| `direkte_duelle` | frühere Duelle zweier Teams |
| `ausfaelle` | Verletzte und Gesperrte eines Teams |
| `tabelle` | Tabelle mit xG und xPts |
| `kickbase` | erwartete Kickbase-Punkte, Marktwert, Trend, Punkte pro Million; `auswahl` = alle, markt oder kader |
| `champions_league` | eine CL-Runde mit Prognosen, Tipps, Elo, Kaderwerten und Bilanz; ohne Angaben die aktuelle, mit `saison` allein die Rundenliste |
| `wettbewerb` | Runde der 2. Bundesliga (`D2`), des DFB-Pokals (`DFB`) oder der CL mit Prognosen und Tipps |
| `tabelle_2_liga` | Tabelle der 2. Bundesliga mit Modell-Platz und Hochrechnung (Aufstieg, Relegation, Abstieg) |
| `cl_tabelle` | Tabelle der CL-Ligaphase mit Modell-Platz und Hochrechnung (Achtelfinale, Play-offs, Aus) |
| `anreise` | nächstes Spiel eines Teams mit Stadion, Ankunftszeit (1 Std. vor Anpfiff) und Google-Maps-Link für Bus und Bahn; `start` = wo man gerade ist |
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
| `fussballdb historie` | Ältere Saisons 1993/94 bis 2013/14 nur zum Nachschlagen laden (Ergebnisse, Statistik, Quoten) |
| `fussballdb ensure` | Prüfen und nur nötige Schritte ausführen (`--voll`: alle, `--ohne-langsame`: ohne Verletzungshistorie und Kickbase-Punkte) |
| `fussballdb status` | Anzeigen, was aktuell ist und was fehlt |
| `fussballdb europa` | Champions League: Europapokal- und Ligaspiele, Kaderwerte aus 30 Ländern, Wappen laden (`--no-werte` ohne Kaderwerte) |
| `fussballdb cl-prognosen` | Prognosen für CL, 2. Liga und Pokal: Rückblick für gespielte Runden, live für offene (`--force` rechnet alle neu, `--wettbewerb D2`) |
| `fussballdb erinnerung` | Mac-Mitteilung mit den Tipps, wenn der Spieltag in < 3 Std. beginnt (`--test` sofort) |
| `fussballdb cl-test` | CL-Prognose rückwirkend testen (Modell, Varianten, Grundverteilung, Tipp-Punkte) |
| `fussballdb update` | Alle schnellen Schritte (wie `ensure --voll --ohne-langsame`) |
| `fussballdb ingest -s 2026` | Einzelne Saison(s) importieren |
| `fussballdb absences` | Verletzte und Sperren neu laden |
| `fussballdb predict -n 2` | Prognosen für die nächsten 2 Spieltage |
| `fussballdb backtest` | Modell rückwirkend gegen Ergebnisse und Wettmarkt testen (`--ausfaelle verletzte/keine/aufstellung`) |
| `fussballdb logos` | Vereinswappen laden (Transfermarkt, ersatzweise OpenLigaDB) nach `web/public/logos` |
| `fussballdb snapshot` | Verletzte und Aufstellungen sichern (täglich per launchd) |
| `fussballdb verletzungshistorie` | Verletzungshistorie aller Spieler seit 2023/24 laden (~30 Min. beim ersten Mal) |
| `fussballdb verletzungen-test` | Ausfälle aus der Verletzungshistorie im Rückblick-Test |
| `fussballdb kickbase-login` | Bei Kickbase anmelden (alternativ im Kickbase-Tab; gespeichert wird nur das Token) |
| `fussballdb kickbase` | Kickbase-Spieler mit Punkte- und Marktwert-Verlauf, Markt und Kader der Liga laden |
| `fussballdb kaderwerte` | Kaderwerte von Transfermarkt laden (läuft auch in `update`) |
| `fussballdb kaderwert-test` | Kaderwert als Startstärke im Rückblick-Test |
| `fussballdb kalibrierung` | Vorhergesagte gegen eingetretene Häufigkeiten (Heim, Remis, Gast, Über 2,5) |
| `fussballdb tipp-test` | Tipp-Regeln im Rückblick vergleichen |
| `fussballdb belastung-test` | Europapokal-Belastung im Rückblick-Test (`--tage`) |
| `fussballdb cl-xg-test` | CL: europaweites xG-Modell gegen die Elo im Rückblick-Test |
| `fussballdb elo-historie-test` | Elo mit Vorgeschichte ab 1993/94 gegen Elo ab 2014/15 (verworfen) |
| `fussballdb startelf-test` | Startelf-Korrektur (Kickbase-Punkte, FotMob-Noten, xG+xA) im Rückblick, auch zusammen mit den verworfenen Erweiterungen (noch nicht übernommen) |
| `fussballdb abschluss-test` | Über-/Unterperformance (Tore gegenüber xG) als Faktor im Rückblick-Test (`--kombi`: zusammen mit den verworfenen Erweiterungen) |
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
| CL-Ausfälle | CL-Spiele in den nächsten 7 Tagen und letzter Abruf älter als 20 Std. | 6 Std. |
| TV-Sender (DE, AT) | Spiele in den nächsten 7 Tagen und letzter Abruf älter als 20 Std. | 6 Std. |
| Spielberichte für die Suche | gespielte Spiele ohne Bericht oder Embedding, Berichte der letzten 14 Tage älter als 20 Std. | 6 Std. |
| Reihenfolge wie bei Kicktipp | Spiele der Saison ohne Position oder letzter Abruf älter als 3 Tage | 12 Std. |
| Spielorte (Stadion, Kapazität) | gespielte Spiele der Saison ohne eingefrorenen Ort oder offene der nächsten 14 Tage älter als 20 Std. | 6 Std. |
| Wetter zur Spielzeit | Vorhersage älter als 6 Std. oder Spiel vorbei und noch nicht gemessen | 3 Std. |
| Aufstellung und Momentum (FotMob) | gespielte Spiele mit FotMob-ID ohne eingefrorene Seite, offene der nächsten 2 Tage älter als 1 Std. | 1 Std. |
| Champions League | CL-Spiel ohne Ergebnis, Ligaspiele älter als 4 Tage, offene Spiele ohne Prognose oder Prognosen älter als 24 Std.; lädt Kaderwerte nach, wenn der neueste älter als 30 Tage ist (nur wenn `fussballdb europa` einmal lief) | 6 Std. |
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
   um 6 %. Verletzte live aus der aktuellen Transfermarkt-Liste, ergänzt um Spieler, die Kickbase als verletzt
   oder im Aufbautraining führt und die bei Transfermarkt (noch) fehlen (`reason` „… (laut Kickbase)“; nicht
   im Rückblick getestet, weil es keinen alten Kickbase-Status gibt), im Rückblick aus der Verletzungshistorie
   zum Stichtag (ab 2023/24). Sperren aus den Karten des letzten Spiels: Rot/Gelb-Rot oder die
   5./10./15. Gelbe der Saison (seit 2014/15). Understat unterscheidet Gelb-Rot und glatt Rot nicht,
   längere Sperren nach glatt Rot sind deshalb nur für das nächste Spiel erfasst.
6. **Europapokal-Belastung**: Hatte ein Team in den 4 Tagen vor dem Bundesliga-Spiel ein Spiel in der
   Champions oder Europa League, sinkt seine Torerwartung um 10 % (`features/euro_load.py`, Spielplan aus
   der CL-Datenbank, also ab 2024/25; die Europa League ist nur für 2024/25 erfasst).

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
| Über-/Unterperformance der letzten 5 Spiele (Tore ÷ xG als Faktor auf die Torerwartung, `fussballdb abschluss-test`) | 2021–26: +0,0085 | verworfen; in keiner der 11 Saisons besser. Mit Dämpfung (5 xG) +0,0035, mit Gegentoren ÷ xGA +0,0165 |
| Abschluss-Faktor zusammen mit den einzeln verworfenen Erweiterungen (Heimvorteil je Team, Duelle, Remis-Kalibrierung, Halbwertszeit 3 Mon., Tor-Skalierung; einzeln und alle zusammen, `fussballdb abschluss-test --kombi`) | +0,0006 bis +0,0095 | verworfen; in jeder der 21 Kombinationen schlechter als ohne Faktor, keine Kombination besser als das aktuelle Modell. Am knappsten: Tor-Skalierung allein −0,0005 (89 % der Ziehungen), aber im Einstellzeitraum schlechter und nur in 5 von 11 Saisons besser, deshalb nicht übernommen |
| Abschlussstärke über 1 Jahr, gedämpft (10 bzw. 20 xG), auch mit Gegentoren | +0,0010 bis +0,0033 | verworfen; besser in höchstens 3 % der Ziehungen. Wer zuletzt über oder unter seinem xG lag, tut das danach nicht weiter, reines xG bleibt besser |
| Europapokal-Belastung: Europapokalspiel in den 4 Tagen davor, Torerwartung −10 % (`fussballdb belastung-test`) | betroffene Spiele −0,0043 | übernommen; 103 Spiele 2024–2026, in allen 3 Saisons besser, 99 % der Ziehungen. −15 bis −25 % waren noch besser, 10 % ist bewusst vorsichtig. Kontrolle: dieselben Teams ohne Europapokal davor abzuwerten schadet (+0,0057), es ist also die Belastung und keine generelle Überschätzung |
| Europapokal-Belastung mit 3 statt 4 Tagen | −0,0019 | schwächer (62 Spiele, 81 %); 4 Tage erfassen auch Dienstag → Samstag |
| Spielerwert über On/Off (xG für/gegen mit und ohne Spieler auf dem Platz) statt xG+xA | 2023–26: +0,0010 | verworfen; zu verrauscht, weil Stammspieler selten fehlen (`features/onoff.py`) |
| Echte Aufstellung (Obergrenze, Wissen aus der Zukunft) | −0,0006 | nur zur Einordnung: Ausfälle sind kaum noch ein Hebel |
| Startelf-Korrektur: Stärke der aufgebotenen gegen die übliche Elf (Startelf steht 1 Std. vor dem Anpfiff fest), Spielerstärke aus FotMob-Noten, Kickbase-Punkten, xG+xA oder gemischt, k 0,1–0,4, zusätzlich zu den Ausfällen oder statt ihrer (`fussballdb startelf-test`, Einstellen 2024/25, Test ab 2025/26) | allein: Noten/Mischung −0,0002 bis −0,0003 (60–69 %), Kickbase +0,0004 bis +0,0014, xG+xA ±0 | nicht übernommen; zu wenig Daten, Kickbase fehlen ehemalige Spieler (2024/25 nur die Hälfte abgedeckt). Kicktipp-Punkte im Test +0,02 bis +0,03 je Spiel, aber im Einstellzeitraum nicht besser. Ende 2026/27 erneut testen |
| Startelf-Korrektur zusammen mit den verworfenen Erweiterungen (Heimvorteil je Team, Duelle, Remis-Kalibrierung, Halbwertszeit 3 Mon., Tor-Skalierung, alle zusammen) | bestes Paar Duelle + Mischung k 0,1: −0,0010 (90 %), Duelle allein −0,0008 (88 %) | nicht übernommen; der Gewinn kommt fast ganz von den Duellen, die im Einstellzeitraum 2024/25 schlechter waren (+0,0004). Duelle sollten mit der Historie ab 1993/94 neu getestet werden |
| Elo mit Vorgeschichte ab 1993/94 statt ab 2014/15 (nur die Elo, `fussballdb elo-historie-test`) | Einstellen 2015–19: −0,0003, Test 2020–26: +0,0005 | verworfen; im Test in keiner der 7 Saisons besser, 9 % der Ziehungen. Die alten Ergebnisse bleiben reine Anzeige |

## Datenbank

| Tabelle | Inhalt |
|---|---|
| `season`, `team`, `team_alias` | Saisons, Teams, Namen je Quelle |
| `match`, `match_team_stats`, `shot` | Spiele, Statistik je Team (xG, Schüsse, PPDA …), jeder Schuss |
| `odds` | Quoten je Buchmacher, Eröffnung (`is_closing = false`) und Schluss |
| `elo_rating` | Elo je Team und Spiel |
| `player`, `player_match` | Spieler und Einsätze mit Minuten, Toren, Vorlagen, xG, xA, Karten |
| `player_absence` | aktuelle Ausfälle (`active`), `source`: `transfermarkt`, `kickbase` (verletzt oder Aufbautraining, nur wenn Transfermarkt sie nicht führt) oder `karten` (Sperren); jeder Abruf bleibt erhalten |
| `player_injury` | Verletzungshistorie je Spieler (von–bis, verpasste Spiele) |
| `lineup_snapshot` | voraussichtliche und tatsächliche Aufstellungen (Ligainsider) |
| `squad_value` | Kaderwerte je Team und Stichtag |
| `prediction` | Prognosen (`basis` = live oder rueckblick), Tipp, Ausfälle, Begründung als JSON, Ergebnis-Wahrscheinlichkeiten 0:0 bis 9:9 (`score_probs`) |
| `match_report` | Spielbericht je Bundesliga-Spiel mit Volltextindex (`tsv`, Deutsch) und Embedding (`embedding`, pgvector, 768 Dimensionen) |
| `tip_round` | Kicktipp-Tipprunden mit Punkteregel, Tippschluss, Bonuspunkten und Standardrunde |
| `update_log` | jeder Update-Schritt mit Grund, Dauer und Ergebnis |
| `match_venue` | Spielort je Spiel (`competition` BL → `match`, sonst `eu_match`), nach dem Spiel eingefroren (`frozen`) |
| `match_page` | Aufstellung (JSON mit Formation, Positionen, Noten, Ereignissen), Momentum, Tore/Platzverweise und Teamfarben je Spiel laut FotMob, nach dem Spiel eingefroren |
| `match_weather` | Wetter je Spiel zur Spielzeit (`kind` vorhersage oder gemessen) |
| `tv_listing` | TV-Sender je Spiel und Land (`competition` BL → `match`, CL → `eu_match`), wie bei FotMob gelistet; Land `LS` = LiveOnSat |
| `kb_session` | Kickbase-Anmeldung: Token, Ablauf, Ligen, gewählte Liga (nie das Passwort) |
| `kb_player`, `kb_points`, `kb_market_value`, `kb_league_entry` | Kickbase: Spieler, Punkte je Spiel, Marktwert-Verlauf, Markt und Kader der aktiven Liga |
| `eu_team`, `eu_team_alias` | Champions League: Vereine aus ganz Europa (Transfermarkt-ID bei Europapokal-Teilnehmern), Namen je Quelle |
| `eu_match` | Liga- (`competition` = football-data-Kürzel) und Europapokalspiele (`CL`, `EL`) |
| `eu_squad_value` | Kaderwerte je Verein und Stichtag (quartalsweise) |
| `eu_absence` | Verletzte und Gesperrte der CL-Teams je Abruf (`active` = letzter Stand), Anteil am Kaderwert |
| `eu_prediction` | CL-Prognosen (live oder rueckblick) mit Elo, Kaderwerten, Tipp und Begründung |

Direkt abfragen:

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Zugangsdaten:** Benutzer, Passwort und Name der Datenbank stehen nur in `.env` (`POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`), nirgends im Code oder in `docker-compose.yml`. Fehlen sie, bricht
`docker compose` mit einem Hinweis ab und die Python-Befehle melden „Datenbankzugang fehlt“. Postgres übernimmt
das Passwort nur beim ersten Anlegen der Datenbank. Später ändern:

```bash
docker exec -it fussballdb-db-1 psql -U fussball -d fussballdb -c "ALTER ROLE fussball WITH PASSWORD 'neues-passwort'"
```

Danach `POSTGRES_PASSWORD` in `.env` anpassen und die App neu starten
(`docker compose --profile app up -d api web`).

Neue Teams (Aufsteiger) müssen in `src/fussballdb/ingest/team_mapping.py` eingetragen werden. Der
Import bricht mit einer klaren Meldung ab, wenn ein Name unbekannt ist. Danach `uv run fussballdb logos`
ausführen und die Web-App neu bauen (`docker compose --profile app up -d --build web`), damit das
Wappen erscheint.

## Tests

```bash
uv run pytest                          # Modell, API (braucht laufende DB), lokaler Chat
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
15. **Nachtest Qwen 3.6 in 8 Bit**: schneller, aber ungenauer, Qwen 3.8 bleibt.
16. **Champions League**: europaweite Elo aus Liga- und Europapokalspielen mit Kaderwert als Startwert,
    eigener Tab, MCP-Werkzeug, Update-Schritt, Rückblick-Test (ClubElo war nicht erreichbar).

17. **Abschlussstärke getestet** (Tore gegenüber xG der letzten Spiele), allein und zusammen mit allen
    verworfenen Erweiterungen: bringt nichts, bleibt aus.
18. **TV-Sender** in den Kacheln für Deutschland und Österreich, Bundesliga und Champions League, als
    Logos der genauen Kanäle.
19. **Tabelle**: Platzdifferenz zum Modell und geschätzte Abschlusstabelle per Simulation, für die
    Bundesliga und die CL-Ligaphase.
20. **CL genauer**: xG der CL-Spiele (FotMob) und der fünf großen Ligen (Understat), europaweites
    xG-Modell mit Form (70/30 mit der Elo), Ausfälle der CL-Teams als Anzeige.
21. **Europapokal-Belastung** für die Bundesliga (−10 % Torerwartung nach Europapokalspiel).
22. **Chat**: Tipp in der Prognosekarte, offizielle Teamnamen für Wappen.
23. **Tipp-Zettel** (Text und Bild), Erinnerung vor dem Tippschluss, Torschützen-Prognose,
    Kickbase-Aufstellung, 2. Bundesliga und DFB-Pokal.
24. **Legenden** unter allen Tabellen, eindeutige Kurznamen, **Kickbase-Anmeldung im Web** (Token in der
    Datenbank, Datenbank-Port nur lokal).
25. **Spiel-Detailseite** für Bundesliga, 2. Liga, Pokal und CL: Form, Direktvergleich, Tabelle, Ausfälle,
    Aufstellung, Spielstatistik und Quoten. Tipp-Zettel auch im Chat als Box.
26. **Ältere Saisons 1993/94 bis 2013/14** zum Nachschlagen (6.426 Spiele, 14 weitere Vereine), Modell
    bleibt bei den Daten ab 2014/15; Direktvergleich auf der Detailseite nur vor dem Spiel und aufklappbar.
27. **Stadion, Kapazität und Wetter** je Spiel (FotMob, Open-Meteo), eingefroren nach dem Spiel, damit Namen
    und Kapazität dem Spieltag entsprechen. Vor dem Spiel eine Kleidungsempfehlung aus der Vorhersage.
28. **Anreise mit Bus und Bahn**: Google-Maps-Link mit Ankunft eine Stunde vor dem Anpfiff, Start = aktueller
    Standort; im MCP als Werkzeug `anreise`.
29. **Mehrere Kicktipp-Tipprunden**: Regeln von der Kicktipp-Seite, Auswahlfeld für Tipps und Punkte je
    Runde, Prognosen für Extratipps (Meister, Herbstmeister, Plätze 16–18).

30. **Spielberichte** zu allen Bundesliga-Spielen ab 2014/15 aus den Daten, Suche mit Volltext und pgvector im
    Chat, im MCP und auf der Detailseite; SQL-Fehler gehen als lesbare Meldung ans Sprachmodell.
31. **Spielberichte im Zeitungsstil** mit Verlauf je Halbzeit, Tabelle, Serien, Formation und Spieler des Spiels;
    Datenbankzugang nur noch aus `.env`.
32. **Aufstellung auf dem Spielfeld und Momentum** (FotMob) auf der Detailseite, Diagramme in Teamfarben.
Offen:

- **Startelf-Korrektur Ende 2026/27 erneut testen** (`fussballdb startelf-test`, mit `tune=(2024, 2025)`), wenn
  eine Saison mehr FotMob-Noten und vollständige Kickbase-Daten da sind; dazu die direkten Duelle mit der
  Historie ab 1993/94
- **CL-xG-Modell nach der Ligaphase 2026/27 (ab Ende Januar 2027) erneut gegen die Elo testen**
  (`fussballdb cl-xg-test`); hält es nicht, `ACTIVE_XG` in `model/europe.py` auf `None` setzen
- Verletzte der CL-Teams ins Modell nehmen, sobald genug Spieltage zum Testen gesammelt sind
- Weiterkommen in K.-o.-Runden (Hin- und Rückspiel zusammen)
- Chat der Web-App kennt die Champions League noch nicht (MCP schon)
