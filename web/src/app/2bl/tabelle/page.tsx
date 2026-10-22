import { Suspense } from "react";
import { CompTablePage } from "@/components/CompPages";

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tabelle …</p>}>
      <CompTablePage comp="D2" />
    </Suspense>
  );
}
