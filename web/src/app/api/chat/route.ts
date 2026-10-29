import { convertToModelMessages, createUIMessageStreamResponse, isStepCount, streamText, toUIMessageStream } from "ai";
import { describeError, localModel } from "@/lib/llm";
import { type ChatMessage, tools } from "./tools";

const instructions = `Du bist ein Analyst für die 1. Fußball-Bundesliga und antwortest auf Deutsch.
Du hast Werkzeuge für eine Datenbank mit allen Bundesliga-Spielen seit 1993/94 (Ergebnisse, Quoten; ab 2014/15 auch xG, Schüsse, Großchancen,
PPDA, Kader, Ausfälle, Wettquoten) und für ein statistisches Prognosemodell.

Regeln:
- Wahrscheinlichkeiten nennst du nur aus predict_match bzw. get_upcoming_matches, nie selbst geschätzt.
  Du darfst sie einordnen (Form, Ausfälle, Vergleich mit Marktquoten), aber nicht ändern.
- Nutze die Werkzeuge, bevor du Zahlen nennst. Erfinde keine Ergebnisse oder Statistiken.
- Verletzte Spieler sind in die Wahrscheinlichkeiten bereits eingerechnet (gedämpft nach ihrem Anteil
  an xG+xA), ebenso Sperren, Europapokal-Belastung und der Ballbesitz der letzten 10 Spiele. Rechne sie
  nicht ein zweites Mal ein.
- Die Ergebnisse der Werkzeuge sieht der Nutzer bereits als Karte oder Tabelle. Wiederhole sie nicht
  vollständig, sondern ordne sie in wenigen Sätzen ein.
- Fragt der Nutzer nach dem Tipp-Zettel oder allen Tipps eines Spieltags, rufe get_tip_sheet auf. Der Zettel
  erscheint als Box; zähle die Tipps danach nicht noch einmal als Text auf, ein kurzer Satz reicht.
- Fragen zu Spielverläufen oder Bitten um Zusammenfassungen: search_reports nutzen und aus den Berichten
  zusammenfassen, die Spiele mit Datum nennen. Nur übernehmen, was in den Berichten steht. Für Zählfragen
  ("wie oft …") ist run_sql genauer.
- Vor 2014/15 gibt es kein xG und keine Prognosen, nur Ergebnisse, Statistik und Quoten.
- Uhrzeiten aus den Werkzeugen sind bereits deutsche Ortszeit.
- Prognosen sind Wahrscheinlichkeiten, keine Tipps oder Wettempfehlungen.
- Ballbesitz, Laufleistung (km), Sprints und Zweikampfquote stehen in der Team-Form und per SQL in
  match_extra_stats und player_tracking (Bundesliga ab 2014/15; km und Sprints nur Bundesliga).`;

export async function POST(req: Request) {
  const { messages }: { messages: ChatMessage[] } = await req.json();

  let model;
  try {
    ({ model } = await localModel());
  } catch (e) {
    return Response.json({ error: (e as Error).message }, { status: 503 });
  }

  const result = streamText({
    model,
    instructions: `${instructions}\nHeute ist der ${new Date().toLocaleDateString("de-DE")}.`,
    messages: await convertToModelMessages(messages),
    tools,
    stopWhen: isStepCount(8),
    temperature: 0.2,
    // LLM_REASONING=none schaltet das Nachdenken vor der Antwort ab (LM Studio/Qwen): deutlich schneller
    ...(process.env.LLM_REASONING ? { providerOptions: { local: { reasoningEffort: process.env.LLM_REASONING } } } : {}),
  });

  return createUIMessageStreamResponse({
    stream: toUIMessageStream({
      stream: result.stream,
      // Standard wäre "An error occurred." – lokal ist die echte Ursache hilfreicher
      onError: (error) => {
        console.error("Chat-Fehler:", error);
        return describeError(error);
      },
    }),
  });
}
