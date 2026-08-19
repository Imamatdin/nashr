"use client";

// The interior shell (P3.6). Every signed-in view renders inside it: a sticky
// rail on the left, a collapsed bar below 880px. No gold lives here — the one
// gilded element per viewport belongs to each view's primary action.

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { clearSession } from "@/lib/session";

// The short label is the topbar's: the full row (wordmark + two links +
// Chiqish) overflows a 375px Telegram webview at the sidebar wording.
const NAV: ReadonlyArray<{
  key: "projects" | "new";
  href: string;
  label: string;
  short: string;
}> = [
  { key: "projects", href: "/projects", label: "Loyihalar", short: "Loyihalar" },
  { key: "new", href: "/new", label: "Yangi loyiha", short: "Yangi" },
];

export function AppChrome({
  children,
  active,
}: {
  children: ReactNode;
  active: "projects" | "new";
}) {
  const router = useRouter();

  function signOut() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="dark app-frame">
      <aside className="app-sidebar">
        <Link href="/projects" className="app-brand">
          Nashr
        </Link>
        <nav className="app-nav">
          {NAV.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              className="app-nav-link"
              data-active={item.key === active ? "true" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="app-nav-footer">
          <button type="button" className="app-logout" onClick={signOut}>
            Chiqish
          </button>
          <p className="app-tag">Manbaga asoslangan nashrlar</p>
        </div>
      </aside>

      <header className="app-topbar">
        <Link href="/projects" className="app-brand">
          Nashr
        </Link>
        <nav className="app-topbar-links">
          {NAV.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              className="app-nav-link"
              data-active={item.key === active ? "true" : undefined}
            >
              {item.short}
            </Link>
          ))}
          <button type="button" className="app-logout" onClick={signOut}>
            Chiqish
          </button>
        </nav>
      </header>

      <main className="app-main">{children}</main>
    </div>
  );
}
