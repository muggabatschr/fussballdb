import { Suspense } from "react";
import { ClTablePage } from "./ClTablePage";

export default function Page() {
  return (
    <Suspense fallback={<p className="text-muted">Lade Tabelle …</p>}>
      <ClTablePage />
    </Suspense>
  );
}
