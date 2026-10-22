// Kickbase-Anmeldung: leitet an die Python-API weiter (Status, Anmelden, Liga wählen, Abmelden).
// E-Mail und Passwort werden nur durchgereicht und nirgends gespeichert oder protokolliert.
const BASE = process.env.FUSSBALL_API_URL || "http://127.0.0.1:8000";
const ACTIONS = new Set(["status", "login", "liga", "logout"]);

async function forward(action: string, init?: RequestInit) {
  if (!ACTIONS.has(action)) return Response.json({ detail: "Unbekannte Aktion" }, { status: 404 });
  try {
    const res = await fetch(`${BASE}/kickbase/${action}`, { ...init, cache: "no-store" });
    const body = await res.json().catch(() => ({}));
    return Response.json(body, { status: res.status });
  } catch {
    return Response.json({ detail: "Python-API nicht erreichbar." }, { status: 503 });
  }
}

export async function GET(_req: Request, ctx: RouteContext<"/api/kickbase/[action]">) {
  const { action } = await ctx.params;
  return forward(action);
}

export async function POST(req: Request, ctx: RouteContext<"/api/kickbase/[action]">) {
  const { action } = await ctx.params;
  const body = action === "logout" ? "{}" : await req.text();
  return forward(action, { method: "POST", headers: { "Content-Type": "application/json" }, body });
}
