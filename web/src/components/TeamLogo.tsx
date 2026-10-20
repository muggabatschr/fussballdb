import Image from "next/image";
import { resolveTeam } from "@/lib/teams";

/** Vereinswappen (lokal unter /public/logos, geladen mit `fussballdb logos`). */
export function TeamLogo({ name, size = 20 }: { name: string; size?: number }) {
  const src = resolveTeam(name)?.info.logo;
  if (!src) return null;
  // Wappen sind 139 × 181 px; Breite aus dem Seitenverhältnis
  return (
    <Image
      src={src}
      alt=""
      width={Math.round((size * 139) / 181)}
      height={size}
      className="inline-block shrink-0 object-contain"
    />
  );
}
