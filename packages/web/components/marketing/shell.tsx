// The marketing shell: header, footer, and the light ground they sit on.
//
// It exists as a component rather than living only in the route group's layout
// because "/" stays at app/page.tsx — outside the group — so both entry points
// have to wrap their content in exactly the same chrome.

import type { ReactNode } from "react";
import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";
import "./marketing.css";

export function MarketingShell({ children }: { children: ReactNode }) {
  return (
    <div data-marketing-root className="theme-light mkt">
      <SiteHeader />
      <main className="mkt-main">{children}</main>
      <SiteFooter />
    </div>
  );
}

export default MarketingShell;
