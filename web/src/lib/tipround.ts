// Gewählte Tipprunde (Cookie "tipprunde", gesetzt vom Auswahlfeld). Nur serverseitig verwenden.
import { cookies } from "next/headers";

export const TIP_ROUND_COOKIE = "tipprunde";

export async function selectedTipRound(): Promise<string | undefined> {
  return (await cookies()).get(TIP_ROUND_COOKIE)?.value || undefined;
}
