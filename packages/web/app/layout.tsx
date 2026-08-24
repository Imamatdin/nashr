import type { Metadata } from "next";
import { IBM_Plex_Mono, Literata, Source_Sans_3 } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";
import { cn } from "@/lib/utils";

// The only three families that exist: display serif, UI sans, machine mono.
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
    // suppressHydrationWarning: inside the (app) group the Telegram bridge
    // stamps --tg-viewport-* on <html> and the no-flash script stamps the theme
    // class before React hydrates. Attribute-level and expected, not a bug.
    //
    // The theme system itself lives in app/(app)/layout.tsx, NOT here: this
    // layout also wraps the static marketing site, which must ship no theme JS
    // at all.
    <html
      lang="uz"
      suppressHydrationWarning
      className={cn(literata.variable, sourceSans.variable, plexMono.variable, "font-sans")}
    >
      <body>{children}</body>
    </html>
  );
}
