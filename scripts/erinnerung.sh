#!/usr/bin/env bash
# Erinnerung vor dem Tippschluss (Mac-Mitteilung mit den Tipps), alle 30 Minuten per launchd.
# Läuft die Datenbank nicht, passiert nichts (Docker wird dafür nicht gestartet).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$HOME/.docker/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
docker compose ps --status running --services 2>/dev/null | grep -qx db || exit 0
uv run fussballdb erinnerung
