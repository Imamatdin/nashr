// The marketing header. Server component on purpose: no disclosure button, no
// pathname hook, no client bundle. Below 760px the nav drops to its own
// scroll strip under the wordmark (see marketing.css) rather than a menu.

import Link from "next/link";
import { APP, NAV, ROUTES, startHref } from "./links";

export function SiteHeader() {
  return (
    <header className="mkt-head">
      <div className="mkt-wrap mkt-head-inner">
        <Link href={ROUTES.home} className="mkt-brand">
          Nashr
        </Link>

        <nav className="mkt-nav" aria-label="Asosiy bo‘limlar">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className="mkt-navlink">
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="mkt-actions">
          <Link href={APP.login} className="mkt-navlink">
            Kirish
          </Link>
          <Link href={startHref()} className="mkt-btn">
            Boshlash
          </Link>
        </div>
      </div>
    </header>
  );
}

export default SiteHeader;
