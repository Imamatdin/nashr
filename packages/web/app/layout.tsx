import type { Metadata } from "next";
import Script from "next/script";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nashr",
  description: "Source-grounded academic presentations and articles",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="uz">
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
