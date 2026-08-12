import type { Metadata } from "next";
import { IBM_Plex_Mono, Literata, Source_Sans_3 } from "next/font/google";
import Script from "next/script";
import type { ReactNode } from "react";
import "./globals.css";
import { cn } from "@/lib/utils";

// §3 of docs/DESIGN_DIRECTION.md — the only three families that exist.
// Self-hosted via next/font (downloaded at build, served from our origin).
// Cyrillic subsets cover RU/KAA; latin-ext covers oʻ/gʻ/ń/á forms.
const literata = Literata({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  variable: "--font-literata",
  display: "swap",
});

const sourceSans = Source_Sans_3({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  variable: "--font-source-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext", "cyrillic"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

// Icons are conventional files, not config: app/icon.svg and app/apple-icon.png
// are picked up by the App Router automatically — declaring them here would
// only fight the convention.
export const metadata: Metadata = {
  title: "Nashr — manbaga asoslangan taqdimotlar",
  description:
    "Nashr har bir fikrni manbaga bog’laydi: yuklangan manbalardan bir urinishda nashr sifatidagi taqdimot. HTML, PDF va PPTX — uchala format ham asosiy.",
  openGraph: {
    type: "website",
    locale: "uz_UZ",
    siteName: "Nashr",
    title: "Nashr — manbaga asoslangan taqdimotlar",
    description:
      "Har bir da’vo manbaga bog’lanadi, tanqidchi to’qimani rad etadi. Ma’ruzangiz savolga dosh beradi.",
    images: [{ url: "/og.jpg", width: 1200, height: 630, alt: "Nashr" }],
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning: the Telegram bridge stamps --tg-viewport-* on
    // <html> before hydration; attribute-level and expected, not a bug.
    <html
      lang="uz"
      suppressHydrationWarning
      className={cn(literata.variable, sourceSans.variable, plexMono.variable, "font-sans")}
    >
      <body>
        {/* Telegram Mini App bridge (panel finding): window.Telegram.WebApp only
            exists if this script loads — without it the Telegram door silently
            never fires and every in-Telegram user falls through to email. */}
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
        {children}
      </body>
    </html>
  );
}
