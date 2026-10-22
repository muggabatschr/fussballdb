import { Suspense } from "react";
import { TipsPage } from "./TipsPage";

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tipps …</p>}>
      <TipsPage />
    </Suspense>
  );
}
