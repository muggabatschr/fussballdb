import Link from "next/link";

const TABS = [
  { key: "BL", href: "/", label: "Bundesliga" },
  { key: "D2", href: "/2bl", label: "2. Liga" },
  { key: "DFB", href: "/pokal", label: "Pokal" },
  { key: "CL", href: "/cl", label: "CL" },
] as const;

/** Umschalten zwischen den Wettbewerben über den Spieltags- und Rundenansichten. */
export function CompetitionTabs({ active }: { active: (typeof TABS)[number]["key"] }) {
  return (
    <nav className="-mt-2 flex gap-1 overflow-x-auto whitespace-nowrap text-sm" aria-label="Wettbewerb">
      {TABS.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          className={`rounded-md px-2.5 py-1 ${t.key === active ? "bg-accent/15 font-medium text-foreground" : "text-muted hover:text-foreground"}`}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
