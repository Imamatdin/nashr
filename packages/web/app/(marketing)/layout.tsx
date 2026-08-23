// The marketing shell. Light permanently — the site has no theme toggle and a
// dark-preference visitor gets the same paper ground (see marketing.css for
// how the document itself is pinned). Server component: the header, the
// footer and every interior page render with no client bundle at all.

import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SiteFooter } from "@/components/marketing/site-footer";
import { SiteHeader } from "@/components/marketing/site-header";
import "@/components/marketing/marketing.css";

export const metadata: Metadata = {
  title: {
    default: "Nashr — manbaga asoslangan taqdimotlar",
    template: "%s — Nashr",
  },
};

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div data-marketing-root className="theme-light mkt">
      <SiteHeader />
      <main className="mkt-main">{children}</main>
      <SiteFooter />
    </div>
  );
}
