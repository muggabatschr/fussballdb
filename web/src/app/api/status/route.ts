// Update-Status der Python-API für den Hinweis in der Oberfläche (der Browser erreicht die API nicht direkt)
import { api } from "@/lib/api";

export async function GET() {
  try {
    return Response.json(await api<unknown>("/status"));
  } catch (e) {
    return Response.json({ error: (e as Error).message }, { status: 503 });
  }
}
