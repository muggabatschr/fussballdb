import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { extractReasoningMiddleware, wrapLanguageModel } from "ai";

export const LLM_BASE_URL = process.env.LLM_BASE_URL || "http://127.0.0.1:1234/v1";
const CONFIGURED_MODEL = process.env.LLM_MODEL || undefined;

const provider = createOpenAICompatible({ name: "local", baseURL: LLM_BASE_URL });

export class LlmUnavailableError extends Error {}

/**
 * Fragt bei jeder Anfrage den lokalen Server nach seinen Modellen (lokal, kostet kaum Zeit).
 * So fällt sofort auf, wenn der Server aus ist oder ein anderes Modell geladen wurde.
 */
async function resolveModelId(): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${LLM_BASE_URL}/models`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
  } catch {
    throw new LlmUnavailableError(
      `Kein lokaler Modellserver unter ${LLM_BASE_URL} erreichbar. In LM Studio den Server starten und ein Modell laden.`,
    );
  }
  const { data } = (await res.json()) as { data: { id: string }[] };
  const available = data.map((m) => m.id).filter((id) => !id.toLowerCase().includes("embed"));
  if (CONFIGURED_MODEL) {
    if (available.length && !available.includes(CONFIGURED_MODEL)) {
      throw new LlmUnavailableError(
        `Modell "${CONFIGURED_MODEL}" (LLM_MODEL) ist nicht verfügbar. Verfügbar: ${available.join(", ")}`,
      );
    }
    return CONFIGURED_MODEL;
  }
  if (!available.length) throw new LlmUnavailableError("Der lokale Server meldet kein geladenes Modell.");
  return available[0];
}

export async function localModel() {
  const id = await resolveModelId();
  // Denkmodelle wie Qwen3 schreiben ihren Gedankengang in <think>-Tags; der landet so als Reasoning-Teil
  return {
    id,
    model: wrapLanguageModel({ model: provider(id), middleware: extractReasoningMiddleware({ tagName: "think" }) }),
  };
}

/** Fehler aus dem Stream in eine verständliche Meldung übersetzen (App läuft nur lokal). */
export function describeError(error: unknown): string {
  const text = error instanceof Error ? `${error.message} ${String(error.cause ?? "")}` : String(error);
  if (/ECONNREFUSED|fetch failed|Cannot connect/i.test(text)) {
    return `Der lokale Modellserver (${LLM_BASE_URL}) hat die Verbindung abgelehnt. Läuft der Server in LM Studio noch?`;
  }
  if (/context length|context window|too many tokens/i.test(text)) {
    return "Der Verlauf ist zu lang für das Modell. Bitte die Seite neu laden und neu beginnen.";
  }
  return error instanceof Error ? error.message : text || "Unbekannter Fehler";
}
