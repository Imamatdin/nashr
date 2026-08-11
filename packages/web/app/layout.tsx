import type { Metadata } from "next";
import { Literata, Manrope } from "next/font/google";
import Script from "next/script";
import type { ReactNode } from "react";
import "./globals.css";

// Self-hosted via next/font (downloaded at build, served from our origin —
// no runtime Google request). Cyrillic subsets cover RU and the Cyrillic
// halves of UZ/KAA; latin-ext covers oʻ/gʻ forms.
const manrope = Manrope({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  variable: "--font-manrope",
  display: "swap",
});

const literata = Literata({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  variable: "--font-literata",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Nashr — manbaga asoslangan taqdimotlar",
  description:
    "Yuklangan manbalardan bir urinishda studiya sifatidagi taqdimot va ilmiy maqolalar. O'zbekiston uchun.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="uz" className={`${manrope.variable} ${literata.variable}`}>
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
