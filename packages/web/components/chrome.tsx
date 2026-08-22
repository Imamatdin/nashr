"use client";

// The interior shell. Every signed-in view renders inside it: the ported
// sidebar rail on the left and a raised panel on the right; below 880px the
// rail is replaced by a topbar. Pages own their own no-session redirect.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { FolderOpen, PenLine } from "lucide-react";
import SidebarNav, { type SidebarNavItem, type SidebarRecent } from "@/components/bui/sidebar-nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { clearSession, loadSession } from "@/lib/session";
import { createRlsClient } from "@/lib/supabase";

const NAV: ReadonlyArray<SidebarNavItem> = [
  {
    key: "projects",
    label: "Loyihalar",
    href: "/projects",
    icon: <FolderOpen size={17} strokeWidth={1.75} aria-hidden />,
  },
  {
    key: "new",
    label: "Yangi",
    href: "/new",
    icon: <PenLine size={17} strokeWidth={1.75} aria-hidden />,
  },
];

type ProjectRow = { id: string; title: string | null };

export function AppChrome({
  children,
  active,
}: {
  children: ReactNode;
  active: "projects" | "new";
}) {
  const router = useRouter();
  const [recents, setRecents] = useState<ReadonlyArray<SidebarRecent>>([]);

  useEffect(() => {
    let cancelled = false;
    async function loadRecents() {
      const session = loadSession();
      if (!session) return;
      const { data } = await createRlsClient(session.accessToken)
        .from("projects")
        .select("id,title")
        .order("created_at", { ascending: false })
        .limit(12);
      if (cancelled || !data) return;
      setRecents(
        (data as ProjectRow[]).map((row) => ({
          id: row.id,
          label: row.title?.trim() || "Nomsiz loyiha",
          href: `/projects/${row.id}`,
        })),
      );
    }
    void loadRecents();
    return () => {
      cancelled = true;
    };
  }, []);

  function signOut() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="app-frame">
      <div className="app-sidebar">
        <SidebarNav
          brand={{ name: "Nashr" }}
          nav={NAV}
          activeNav={active}
          recents={recents}
          onSignOut={signOut}
          footer={(collapsed) => <ThemeToggle compact={collapsed} vertical={collapsed} />}
        />
      </div>

      <header className="app-topbar">
        <Link href="/projects" className="app-brand">
          Nashr
        </Link>
        <nav className="app-topbar-links">
          {NAV.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              data-active={item.key === active ? "true" : undefined}
            >
              {item.label}
            </Link>
          ))}
          <ThemeToggle compact />
          <button type="button" onClick={signOut}>
            Chiqish
          </button>
        </nav>
      </header>

      <main className="app-panel">{children}</main>
    </div>
  );
}
