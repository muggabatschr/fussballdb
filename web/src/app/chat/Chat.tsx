"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "@/app/api/chat/tools";
import { ToolResult } from "./ToolResult";

const examples = [
  "Wie stehen die Chancen beim nächsten Bayern-Spiel?",
  "Welche Teams haben mehr Punkte als ihre xG-Werte hergeben?",
  "Wie ist die Form von Dortmund und wer fällt aus?",
];

export function Chat() {
  const [input, setInput] = useState("");
  const { messages, sendMessage, status, stop, error, regenerate } = useChat<ChatMessage>({
    transport: new DefaultChatTransport({ api: "/api/chat" }),
  });
  const busy = status === "submitted" || status === "streaming";

  const send = (text: string) => {
    if (!text.trim() || busy) return;
    sendMessage({ text });
    setInput("");
  };

  return (
    <div className="flex min-h-[70vh] flex-col">
      <div className="flex-1 space-y-4">
        {messages.length === 0 && (
          <div className="space-y-3">
            <h1 className="text-xl font-semibold">Frag die Daten</h1>
            <p className="text-sm text-muted">
              Das lokale Sprachmodell holt sich Zahlen aus der Datenbank und dem Prognosemodell.
            </p>
            <div className="flex flex-wrap gap-2">
              {examples.map((e) => (
                <button
                  key={e}
                  onClick={() => send(e)}
                  className="rounded-full border border-border bg-surface px-3 py-1 text-sm hover:border-accent"
                >
                  {e}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : "space-y-3"}>
            {m.parts.map((part, i) => {
              const key = `${m.id}-${i}`;
              if (part.type === "text") {
                return m.role === "user" ? (
                  <div key={key} className="max-w-[80%] rounded-lg bg-accent px-3 py-2 text-sm text-white dark:text-black">
                    {part.text}
                  </div>
                ) : (
                  <div key={key} className="prose-sm max-w-none text-sm leading-relaxed [&_table]:my-2 [&_td]:pr-3 [&_th]:pr-3 [&_th]:text-left [&_ul]:list-disc [&_ul]:pl-5">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
                  </div>
                );
              }
              if (part.type === "reasoning") {
                return (
                  <details key={key} className="text-xs text-muted">
                    <summary className="cursor-pointer">Gedankengang</summary>
                    <p className="mt-1 whitespace-pre-wrap">{part.text}</p>
                  </details>
                );
              }
              if (part.type.startsWith("tool-")) {
                return <ToolResult key={key} part={part as Parameters<typeof ToolResult>[0]["part"]} />;
              }
              return null;
            })}
          </div>
        ))}

        {status === "submitted" && <p className="text-sm text-muted">Denke nach …</p>}
        {error && (
          <div className="flex items-center gap-3 rounded-lg border border-away/40 bg-away/10 p-3 text-sm">
            <span>{error.message.includes("{") ? safeError(error.message) : error.message}</span>
            <button onClick={() => regenerate()} className="underline">
              Erneut versuchen
            </button>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="sticky bottom-0 mt-6 flex gap-2 bg-background py-3"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Frage zur Bundesliga …"
          className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
        {busy ? (
          <button type="button" onClick={() => stop()} className="rounded-lg border border-border px-4 text-sm">
            Stopp
          </button>
        ) : (
          <button type="submit" className="rounded-lg bg-accent px-4 text-sm text-white dark:text-black">
            Senden
          </button>
        )}
      </form>
    </div>
  );
}

function safeError(raw: string) {
  try {
    return (JSON.parse(raw) as { error?: string }).error ?? raw;
  } catch {
    return raw;
  }
}
