import Link from "next/link";

/** „Aktuell“: springt zum aktuellen Spieltag bzw. zur aktuellen Runde. Bleibt unsichtbar im Layout, wenn man schon
 * dort ist, damit Auswahl und Pfeile beim Blättern nicht verrutschen. Am Rechner links vor der Saison, auf dem
 * Handy vor dem Tipp-Zettel (die Zeile mit den Auswahlfeldern wäre sonst zu breit). */
export function CurrentLink({ href, show, title, className }: { href: string; show: boolean; title: string; className: string }) {
  return (
    <Link
      href={href}
      className={`whitespace-nowrap ${className} ${show ? "" : "invisible"} sm:rounded-lg sm:border sm:border-border sm:bg-surface sm:px-3 sm:py-1.5 text-sm max-sm:text-muted max-sm:underline sm:hover:border-accent hover:text-foreground`}
      aria-hidden={!show}
      tabIndex={show ? undefined : -1}
      title={title}
    >
      Aktuell
    </Link>
  );
}
