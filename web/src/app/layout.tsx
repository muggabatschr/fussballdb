import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { UpdateBanner } from "@/components/UpdateBanner";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Bundesliga-Prognosen",
  description: "xG, Form, Ausfälle und Prognosen für die 1. Bundesliga",
};

const nav = [
  { href: "/", label: "Spieltag" },
  { href: "/tabelle", label: "Tabelle" },
  { href: "/cl", label: "CL" },
  { href: "/chat", label: "Chat" },
  { href: "/kickbase", label: "Kickbase" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="de" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col font-sans">
        <header className="border-b border-border bg-surface">
          <div className="mx-auto flex max-w-5xl items-center gap-4 whitespace-nowrap px-4 py-3 sm:gap-6">
            <Link href="/" className="truncate font-semibold tracking-tight">
              <span className="sm:hidden">BL-Prognosen</span>
              <span className="hidden sm:inline">Bundesliga-Prognosen</span>
            </Link>
            <nav className="flex shrink-0 gap-4 text-sm text-muted">
              {nav.map((n) => (
                <Link key={n.href} href={n.href} className="hover:text-foreground">
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <UpdateBanner />
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">{children}</main>
        <footer className="mx-auto w-full max-w-5xl px-4 py-6 text-xs text-muted">
          Prognosen sind Wahrscheinlichkeiten aus einem statistischen Modell, keine Wettempfehlung.
        </footer>
      </body>
    </html>
  );
}
