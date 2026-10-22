import { Suspense } from "react";
import { CompRoundPage } from "@/components/CompPages";

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Runde …</p>}>
      <CompRoundPage comp="DFB" />
    </Suspense>
  );
}
