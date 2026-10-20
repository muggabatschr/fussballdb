/** Aufklappbare Begründung zum Tipp ("Warum 2:1?"), erzeugt aus den Zahlen des Modells. */
export function WhyTip({ tip, lines }: { tip: string; lines: string[] }) {
  if (!lines.length) return null;
  return (
    <details className="group text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-1 whitespace-nowrap text-muted hover:text-foreground [&::-webkit-details-marker]:hidden">
        <span className="inline-block transition-transform group-open:rotate-90">▸</span>
        Warum {tip}?
      </summary>
      <ul className="mt-1.5 space-y-1 border-l border-border pl-3 text-muted">
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </details>
  );
}
