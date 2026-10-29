"""Chat über die Fußball-Datenbank. Das Sprachmodell holt sich Zahlen über Werkzeuge
(Datenbank + Prognosemodell) und erklärt sie. Rechnen tut das Prognosemodell, nicht das LLM.

Standard ist ein lokales Modell über eine OpenAI-kompatible Schnittstelle (LM Studio/Bionic, Ollama).
Optional geht es auch mit Claude (LLM_PROVIDER=anthropic)."""

import json
import re
from datetime import date

import httpx

from fussballdb.assistant.tools import TOOLS, Toolbox
from fussballdb.config import ANTHROPIC_MODEL, LLM_PROVIDER, LOCAL_LLM_MODEL, LOCAL_LLM_REASONING, LOCAL_LLM_URL

SYSTEM = """Du bist ein Analyst für die 1. Fußball-Bundesliga und antwortest auf Deutsch.
Du hast Werkzeuge für eine Datenbank mit allen Spielen seit 2024/25 (Ergebnisse, xG, Schüsse,
Großchancen, PPDA, Kader, Ausfälle, Wettquoten) und für ein statistisches Prognosemodell.

Regeln:
- Wahrscheinlichkeiten nennst du nur aus predict_match bzw. get_upcoming_matches, nie selbst geschätzt.
  Du darfst sie einordnen (Form, Ausfälle, Vergleich mit Marktquoten), aber nicht ändern.
- Nutze die Werkzeuge, bevor du Zahlen nennst. Erfinde keine Ergebnisse oder Statistiken.
- Nenne bei Prognosen kurz die wichtigsten Gründe aus den Daten (xG-Form, Ausfälle, Heimvorteil).
- Verletzte Spieler sind in die Wahrscheinlichkeiten bereits eingerechnet (gedämpft nach ihrem Anteil
  an xG+xA), ebenso Sperren, Europapokal-Belastung und der Ballbesitz der letzten 10 Spiele. Rechne sie
  nicht ein zweites Mal ein.
- Fußball ist zufallsbehaftet: Prognosen sind Wahrscheinlichkeiten, keine Tipps oder Wettempfehlungen.
- Ballbesitz, Laufleistung (km), Sprints und Zweikampfquote stehen in get_team_form und in
  match_extra_stats/player_tracking (Bundesliga ab 2014/15; km und Sprints nur Bundesliga).
- Antworte knapp, Zahlen gerne als kleine Tabelle."""

MAX_TOOL_ROUNDS = 12


def _system() -> str:
    return SYSTEM + f"\nHeute ist der {date.today():%d.%m.%Y}."


def _run_tool(tools: Toolbox, name: str, args: dict) -> tuple[str, bool]:
    try:
        return tools.call(name, args), False
    except Exception as exc:  # Fehler an das Modell zurückgeben, damit es korrigieren kann
        return json.dumps({"error": str(exc)}, ensure_ascii=False), True


class LocalChat:
    """Lokales Modell über /v1/chat/completions mit Function Calling."""

    def __init__(self, base_url: str = LOCAL_LLM_URL, model: str = LOCAL_LLM_MODEL,
                 reasoning: str = LOCAL_LLM_REASONING):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=600)
        self.model = model or self._first_model()
        self.extra = {"reasoning_effort": reasoning} if reasoning else {}
        self.tools = Toolbox()
        self.tool_specs = [
            {"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}}
            for t in TOOLS
        ]
        self.messages: list[dict] = [{"role": "system", "content": _system()}]

    def _first_model(self) -> str:
        try:
            models = self.http.get("/models").json()["data"]
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Kein lokaler Modellserver unter {self.http.base_url} erreichbar. "
                "In Bionic/LM Studio den Server starten (Port 1234) und ein Modell laden."
            ) from exc
        chat_models = [m["id"] for m in models if "embed" not in m["id"].lower()]
        if not chat_models:
            raise RuntimeError("Der lokale Server meldet kein geladenes Modell.")
        return chat_models[0]

    def ask(self, question: str, on_tool=None) -> str:
        self.messages.append({"role": "user", "content": question})
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self.http.post("/chat/completions", json={
                "model": self.model, "messages": self.messages, "tools": self.tool_specs,
                "tool_choice": "auto", "temperature": 0.2, **self.extra,
            })
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            self.messages.append({"role": "assistant", "content": msg.get("content") or "",
                                  **({"tool_calls": calls} if calls else {})})
            if not calls:
                # Denkmodelle (Qwen3 u. a.) liefern ihren Gedankengang teils als <think>-Block mit
                return re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    content, _ = json.dumps({"error": "Argumente sind kein gültiges JSON"}), True
                else:
                    if on_tool:
                        on_tool(name, args)
                    content, _ = _run_tool(self.tools, name, args)
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        return "Abgebrochen: zu viele Werkzeugaufrufe hintereinander."


class ClaudeChat:
    """Optional: Claude API (braucht `uv sync --extra claude` und ANTHROPIC_API_KEY)."""

    def __init__(self, model: str = ANTHROPIC_MODEL, effort: str = "medium"):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.tools = Toolbox()
        self.messages: list = []

    def ask(self, question: str, on_tool=None) -> str:
        self.messages.append({"role": "user", "content": question})
        while True:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=_system(),
                tools=TOOLS,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                # Lehnt ein Sicherheitsfilter fälschlich ab, übernimmt serverseitig ein anderes Modell
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                cache_control={"type": "ephemeral"},
            )
            # komplette Antwort anhängen (inkl. Thinking-Blöcken), nicht nur den Text
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "refusal":
                return "Die Anfrage wurde abgelehnt."
            if response.stop_reason != "tool_use":
                return "".join(b.text for b in response.content if b.type == "text")
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if on_tool:
                    on_tool(block.name, block.input)
                content, is_error = _run_tool(self.tools, block.name, dict(block.input))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})


def create_chat(provider: str = LLM_PROVIDER, effort: str = "medium"):
    if provider == "anthropic":
        return ClaudeChat(effort=effort)
    return LocalChat()
