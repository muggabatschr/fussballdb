#!/usr/bin/env bash
# Daten aktualisieren: prüft, was fehlt oder veraltet ist, und lädt nur das Nötige
# (Ergebnisse, xG, Kaderwerte, Verletzte und Aufstellungen, Quoten, Prognosen).
#   scripts/update.sh          nur nötige Schritte
#   scripts/update.sh --voll   alle Schritte
# Läuft täglich per launchd (scripts/de.fussballdb.snapshot.plist), siehe README.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$HOME/.docker/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
echo "=== $(date '+%Y-%m-%d %H:%M') ==="
if ! docker info >/dev/null 2>&1; then
  # Docker Desktop starten und auf die Engine warten (max. 2 Minuten)
  open -a Docker || true
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
fi
docker compose up -d --wait db
uv run fussballdb ensure "$@"
