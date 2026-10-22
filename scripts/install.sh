#!/usr/bin/env bash
# Setzt fussballdb aus dem Repo komplett neu auf: Konfiguration, Datenbank (Postgres in Docker),
# Python- und Web-Abhängigkeiten, Tabellen, Erstimport aller Saisons, Wappen und Prognosen.
# Kann gefahrlos erneut laufen: vorhandene Daten bleiben, es wird nur ergänzt.
#
#   scripts/install.sh              alles einrichten (beim ersten Mal 1–2 Std., v. a. Import und Verletzungshistorie)
#   scripts/install.sh --schnell    ohne die langsamen Schritte (Verletzungshistorie, Kickbase-Punkte, Champions League)
#   scripts/install.sh --ohne-web   ohne npm install für die Web-App
#   scripts/install.sh --launchd    zusätzlich das tägliche Update um 9:30 und die Tipp-Erinnerung einrichten (macOS)
#   scripts/install.sh --mcp        zusätzlich den MCP-Server in Claude Code eintragen
#   scripts/install.sh --app        am Ende API und Web-App in Docker starten (http://localhost:3010)
set -euo pipefail
cd "$(dirname "$0")/.."
PROJEKT="$(pwd)"
export PATH="$HOME/.local/bin:$HOME/.docker/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

SCHNELL=0 WEB=1 LAUNCHD=0 MCP=0 APP=0
for arg in "$@"; do
  case "$arg" in
    --schnell) SCHNELL=1 ;;
    --ohne-web) WEB=0 ;;
    --launchd) LAUNCHD=1 ;;
    --mcp) MCP=1 ;;
    --app) APP=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unbekannte Option: $arg (siehe --help)"; exit 1 ;;
  esac
done

schritt() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fehlt() { echo "Fehlt: $1. $2"; exit 1; }

schritt "Voraussetzungen prüfen"
command -v docker >/dev/null || fehlt "Docker" "Docker Desktop installieren: https://www.docker.com/products/docker-desktop/"
command -v uv >/dev/null || fehlt "uv" "Installieren mit: curl -LsSf https://astral.sh/uv/install.sh | sh"
if [ "$WEB" = 1 ] && ! command -v npm >/dev/null; then
  fehlt "Node.js/npm" "Node.js 24 installieren (z. B. brew install node) oder mit --ohne-web starten."
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker läuft nicht, starte Docker Desktop …"
  open -a Docker 2>/dev/null || true
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || fehlt "laufendes Docker" "Docker Desktop starten und erneut versuchen."
fi
echo "ok"

schritt "Konfiguration"
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env aus .env.example angelegt (leere Werte = Standard). Bei Bedarf anpassen."
else
  echo ".env vorhanden, bleibt unverändert."
fi
if [ "$WEB" = 1 ] && [ ! -f web/.env.local ]; then
  cp web/.env.example web/.env.local
  echo "web/.env.local aus web/.env.example angelegt."
fi

schritt "Datenbank starten (Postgres + pgvector auf Port 5442)"
docker compose up -d --wait db

schritt "Python-Abhängigkeiten"
uv sync

schritt "Tabellen anlegen"
uv run fussballdb init-db

schritt "Spiele importieren (alle Saisons seit 2014/15, beim ersten Mal ~30 Min.)"
if [ "$(docker compose exec -T db psql -U fussball -d fussballdb -Atc 'SELECT count(*) FROM match' 2>/dev/null || echo 0)" -gt 0 ]; then
  echo "Spiele schon vorhanden, nur die laufende Saison wird über das Update ergänzt."
else
  uv run fussballdb ingest
fi

schritt "Kaderwerte, Ausfälle, Quoten, Prognosen"
if [ "$SCHNELL" = 1 ]; then
  uv run fussballdb ensure --ohne-langsame
else
  echo "Die Verletzungshistorie dauert beim ersten Mal rund 40 Minuten."
  uv run fussballdb ensure
fi

if [ "$SCHNELL" = 0 ]; then
  schritt "Champions League (Europapokal, Ligaspiele aus 18 Ländern, Kaderwerte; beim ersten Mal ~1 Std.)"
  uv run fussballdb europa
  uv run fussballdb cl-prognosen
fi

schritt "Vereinswappen"
uv run fussballdb logos

if [ "$WEB" = 1 ]; then
  schritt "Web-App-Abhängigkeiten"
  (cd web && npm install)
fi

if [ "$LAUNCHD" = 1 ]; then
  schritt "Tägliches Update um 9:30 und Tipp-Erinnerung (launchd)"
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  for job in snapshot erinnerung; do
    ZIEL="$HOME/Library/LaunchAgents/de.fussballdb.$job.plist"
    sed -e "s#__PROJEKT__#$PROJEKT#g" -e "s#__HOME__#$HOME#g" "scripts/de.fussballdb.$job.plist" > "$ZIEL"
    launchctl bootout "gui/$(id -u)/de.fussballdb.$job" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$ZIEL"
  done
  echo "eingerichtet, Logs: ~/Library/Logs/fussballdb-snapshot.log und fussballdb-erinnerung.log"
fi

if [ "$MCP" = 1 ]; then
  schritt "MCP-Server in Claude Code eintragen"
  if command -v claude >/dev/null; then
    claude mcp remove fussballdb -s user >/dev/null 2>&1 || true
    claude mcp add fussballdb -s user -- "$(command -v uv)" run --directory "$PROJEKT" fussballdb-mcp
  else
    echo "claude-Befehl nicht gefunden, übersprungen. Eintrag für Claude Desktop siehe README."
  fi
fi

if [ "$APP" = 1 ]; then
  schritt "API und Web-App in Docker starten"
  docker compose --profile app up -d --build
  echo "Web-App: http://localhost:3010"
fi

schritt "Fertig"
uv run fussballdb status
cat <<TEXT

Nächste Schritte:
  Web-App starten:     docker compose --profile app up -d --build   (dann http://localhost:3010)
  Chat lokal:          LM Studio mit Server auf Port 1234 starten, siehe README "Lokales Sprachmodell"
  Kickbase (optional): uv run fussballdb kickbase-login && uv run fussballdb kickbase
  Champions League:    uv run fussballdb europa && uv run fussballdb cl-prognosen   (falls mit --schnell übersprungen)
  Daten aktualisieren: scripts/update.sh
TEXT
