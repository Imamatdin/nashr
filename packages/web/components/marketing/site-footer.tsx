// The marketing footer: the whole sitemap, the two public channels, the legal
// pair. Server component, no client bundle.

import Link from "next/link";
import { ROUTES, SOCIAL } from "./links";

const COLUMNS: ReadonlyArray<{
  title: string;
  links: ReadonlyArray<{ href: string; label: string; external?: boolean }>;
}> = [
  {
    title: "Mahsulot",
    links: [
      { href: ROUTES.presentations, label: "Taqdimot" },
      { href: ROUTES.articles, label: "Maqola" },
      { href: ROUTES.pricing, label: "Narxlar" },
    ],
  },
  {
    title: "Foydalanish",
    links: [
      { href: ROUTES.teachers, label: "O‘qituvchilarga" },
      { href: ROUTES.help, label: "Yordam" },
    ],
  },
  {
    title: "Nashr",
    links: [
      { href: ROUTES.about, label: "Haqida" },
      { href: SOCIAL.telegram, label: "Telegram", external: true },
      { href: SOCIAL.instagram, label: "Instagram", external: true },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="mkt-foot">
      <div className="mkt-wrap">
        <div className="mkt-foot-grid">
          <div>
            <p className="mkt-foot-brand">Nashr</p>
            <p className="mkt-foot-tag">
              Manbaga asoslangan akademik ishlab chiqarish. Har bir da’vo siz bergan hujjatga
              bog‘lanadi.
            </p>
          </div>

          {COLUMNS.map((column) => (
            <div key={column.title} className="mkt-foot-col">
              <h2>{column.title}</h2>
              <ul className="mkt-foot-list">
                {column.links.map((link) => (
                  <li key={link.href}>
                    {link.external ? (
                      <a href={link.href} target="_blank" rel="noreferrer">
                        {link.label}
                      </a>
                    ) : (
                      <Link href={link.href}>{link.label}</Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mkt-foot-base">
          <span>© {new Date().getFullYear()} Nashr</span>
          <div className="mkt-foot-legal">
            <Link href={ROUTES.privacy}>Maxfiylik siyosati</Link>
            <Link href={ROUTES.terms}>Foydalanish shartlari</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}

export default SiteFooter;
