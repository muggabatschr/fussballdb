import Link from "next/link";
import { teamHref } from "@/lib/format";
import { resolveTeam } from "@/lib/teams";
import { TeamLogo } from "./TeamLogo";

/** Wappen + Name in einer Zeile. Bricht nie um; reicht der Platz nicht, wird mit "…" gekürzt.
 *  short: Kurzname ("Gladbach") für enge Stellen, voller Name als Tooltip. */
export function TeamName({
  name,
  short = false,
  link = true,
  logoSize = 20,
  align = "start",
  className = "",
}: {
  name: string;
  short?: boolean;
  link?: boolean;
  logoSize?: number;
  align?: "start" | "end";
  className?: string;
}) {
  const team = resolveTeam(name);
  const full = team?.name ?? name;
  const label = short ? (team?.info.short ?? name) : full;
  const text = <span className="truncate">{label}</span>;
  return (
    <span
      className={`inline-flex min-w-0 max-w-full items-center gap-1.5 whitespace-nowrap ${align === "end" ? "flex-row-reverse" : ""} ${className}`}
      title={full}
    >
      <TeamLogo name={full} size={logoSize} />
      {link ? (
        <Link href={teamHref(full)} className="truncate hover:underline">
          {label}
        </Link>
      ) : (
        text
      )}
    </span>
  );
}
