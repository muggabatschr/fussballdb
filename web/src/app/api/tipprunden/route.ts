// Tipprunden verwalten: leitet an die Python-API weiter (Liste, anlegen, als Standard setzen, löschen).
const BASE = process.env.FUSSBALL_API_URL || "http://127.0.0.1:8000";

async function forward(path: string, init?: RequestInit) {
  try {
    const res = await fetch(`${BASE}/tipprunden${path}`, { ...init, cache: "no-store" });
    return Response.json(await res.json().catch(() => ({})), { status: res.status });
  } catch {
    return Response.json({ detail: "Python-API nicht erreichbar." }, { status: 503 });
  }
}

export async function GET() {
  return forward("");
}

/** body: {action: "add", url, name?} | {action: "standard" | "delete", slug} */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const slug = encodeURIComponent(String(body.slug ?? ""));
  if (body.action === "add") {
    return forward("", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: body.url, name: body.name || null }) });
  }
  if (body.action === "standard") return forward(`/${slug}/standard`, { method: "POST" });
  if (body.action === "delete") return forward(`/${slug}`, { method: "DELETE" });
  return Response.json({ detail: "Unbekannte Aktion" }, { status: 400 });
}
