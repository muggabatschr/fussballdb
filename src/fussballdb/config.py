import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# Leere Werte in .env (wie in .env.example) gelten als nicht gesetzt
DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql+psycopg://fussball:fussball@localhost:5442/fussballdb"
# Chat-Backend: "local" = OpenAI-kompatibler Server auf dem eigenen Rechner (LM Studio/Bionic, Ollama),
# "anthropic" = Claude API (optional, braucht `uv sync --extra claude` und einen API-Schlüssel)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER") or "local"
LOCAL_LLM_URL = os.environ.get("LOCAL_LLM_URL") or "http://localhost:1234/v1"
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "")  # leer = erstes geladenes Modell
# "none" schaltet das Nachdenken vor der Antwort ab (LM Studio, Qwen); leer = Standard des Modells
LOCAL_LLM_REASONING = os.environ.get("LOCAL_LLM_REASONING", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-opus-5-5"
CACHE_DIR = ROOT / ".cache"

# Startjahre der Saisons, die standardmäßig importiert werden (2024 = Saison 2024/25).
# Ab 2014/15, weil Understat (xG, Schüsse, Kader) erst dann beginnt.
DEFAULT_SEASONS = list(range(2014, 2027))

# Punkteregel des Tippspiels: Sieg Tendenz, Sieg Tordifferenz, exaktes Ergebnis, Remis Tendenz.
# Standard = Regel der Tipprunde p-koetzle-tippspiel (Kicktipp "2 - 4 Punkte"): ein richtiges Remis
# mit falschem Ergebnis bringt 3 Punkte. Kicktipp-Standard wäre "2,3,4,2".
TIPP_PUNKTE = tuple(int(x) for x in (os.environ.get("TIPP_PUNKTE") or "2,3,4,3").split(","))
