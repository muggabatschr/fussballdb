import { Suspense } from "react";
import { ErrorBox } from "@/components/Card";
import { ClView } from "@/components/ClView";
import { getClRound, getClRounds, load } from "@/lib/api";

// Aktuelle Runde der neuesten CL-Saison
async function Current() {
  const res = await load(async () => {
    const seasons = await getClRounds();
    const latest = seasons[0];
    return [seasons, await getClRound(latest.season, latest.current_round)] as const;
  });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [seasons, data] = res.data;
  return <ClView seasons={seasons} data={data} />;
}

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Champions League …</p>}>
      <Current />
    </Suspense>
  );
}
