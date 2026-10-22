import { Suspense } from "react";
import { CompTipsPage } from "@/components/CompPages";

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tipps …</p>}>
      <CompTipsPage comp="DFB" />
    </Suspense>
  );
}
