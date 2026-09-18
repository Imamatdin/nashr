"use client";

// The interior shell. Every signed-in view renders inside it: the ported
// sidebar rail on the left and a raised panel on the right; below 880px the
// rail is replaced by a topbar. Pages own their own no-session redirect.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { FolderOpen, PenLine, Wallet } from "lucide-react";
import SidebarNav, {
  type SidebarNavItem,
  type SidebarRecent,
} from "@/components/bui/sidebar-nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { LanguagePicker, useLocale } from "@/components/locale-provider";
import { getBalance } from "@/lib/api";
import { soum } from "@/lib/packages";
import { clearSession, loadSession } from "@/lib/session";
import { createRlsClient } from "@/lib/supabase";
import { useAppSession } from "@/lib/use-session";

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

/**
 * The balance, wherever the user is (G8).
 *
 * Returns `null` — draws nothing at all — while the read is in flight AND if
 * it fails. A placeholder "0 so'm" would tell someone with 40 000 so'm in the
 * ledger that they have none, which is a worse lie than saying nothing; the
 * figure appears only once the server has actually confirmed it.
 */
function useBalance(): number | null {
  const { session, withAuth } = useAppSession();
  const [balance, setBalance] = useState<number | null>(null);
  const ready = session !== null;

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    withAuth((token) => getBalance(token))
      .then((view) => {
        if (!cancelled && view) setBalance(view.balance);
      })
      .catch(() => {
        // Silence is the honest degradation here — see the note above.
      });
    return () => {
      cancelled = true;
    };
  }, [ready, withAuth]);

  return balance;
}

function BalanceChip({
  balance,
  collapsed,
  active,
  label,
}: {
  balance: number;
  collapsed: boolean;
  active: boolean;
  label: string;
}) {
  const amount = soum(balance);
  const rest = active ? "bg-hover-2 text-ink" : "text-ink-2";
  if (collapsed) {
    return (
      <Link
        href="/hisob"
        aria-label={`${label}: ${amount}`}
        title={`${label}: ${amount}`}
        className={`flex size-8 items-center justify-center rounded-[8px] no-underline
          transition-colors duration-150 hover:bg-hover-2 hover:text-ink hover:no-underline ${rest}`}
      >
        <Wallet size={16} strokeWidth={1.75} aria-hidden />
      </Link>
    );
  }
  return (
    <Link
      href="/hisob"
      title={`${label}: ${amount}`}
      className={`mb-1 flex h-8 items-center gap-1.5 rounded-[8px] px-2 no-underline
        transition-colors duration-150 hover:bg-hover-2 hover:text-ink hover:no-underline ${rest}`}
    >
      <Wallet size={16} strokeWidth={1.75} aria-hidden />
      <span className="data-text min-w-0 flex-1 truncate text-[13px]">
        {amount}
      </span>
    </Link>
  );
}

export function AppChrome({
  children,
  active,
}: {
  children: ReactNode;
  active: "projects" | "new" | "hisob";
}) {
  const router = useRouter();
  const { locale } = useLocale();
  const copy = {
    uz: {
      nav: ["Loyihalar", "Yangi"],
      signOut: "Chiqish",
      balance: "Hisob",
      unnamed: "Nomsiz loyiha",
      navigation: "Ish maydoni navigatsiyasi",
      recentProjects: "Oxirgi loyihalar",
      collapse: "Panelni yig‘ish",
      expand: "Panelni ochish",
      search: "Loyihalarni qidirish",
      searchHistory: "Loyihalar tarixidan qidirish",
      closeSearch: "Qidiruvni yopish",
      noProject: "Loyiha topilmadi",
    },
    ru: {
      nav: ["Проекты", "Создать"],
      signOut: "Выйти",
      balance: "Баланс",
      unnamed: "Без названия",
      navigation: "Навигация по рабочему пространству",
      recentProjects: "Недавние проекты",
      collapse: "Свернуть панель",
      expand: "Развернуть панель",
      search: "Искать проекты",
      searchHistory: "Искать в истории проектов",
      closeSearch: "Закрыть поиск",
      noProject: "Проект не найден",
    },
    en: {
      nav: ["Projects", "Create"],
      signOut: "Sign out",
      balance: "Balance",
      unnamed: "Untitled project",
      navigation: "Workspace navigation",
      recentProjects: "Recent projects",
      collapse: "Collapse sidebar",
      expand: "Expand sidebar",
      search: "Search projects",
      searchHistory: "Search project history",
      closeSearch: "Close search",
      noProject: "No project found",
    },
  }[locale];
  const navigation = NAV.map((item, index) => ({
    ...item,
    label: copy.nav[index],
  }));
  const [recents, setRecents] = useState<ReadonlyArray<SidebarRecent>>([]);
  const balance = useBalance();

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
          label: row.title?.trim() || copy.unnamed,
          href: `/projects/${row.id}`,
        })),
      );
    }
    void loadRecents();
    return () => {
      cancelled = true;
    };
  }, [copy.unnamed]);

  function signOut() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="app-frame">
      <div className="app-sidebar">
        <SidebarNav
          brand={{ name: "Nashr" }}
          nav={navigation}
          activeNav={active}
          recents={recents}
          onSignOut={signOut}
          copy={{
            navigation: copy.navigation,
            signOut: copy.signOut,
            recentProjects: copy.recentProjects,
            collapse: copy.collapse,
            expand: copy.expand,
            search: copy.search,
            searchHistory: copy.searchHistory,
            closeSearch: copy.closeSearch,
            noProject: copy.noProject,
          }}
          footer={(collapsed) => (
            <>
              {balance !== null && (
                <BalanceChip
                  balance={balance}
                  collapsed={collapsed}
                  active={active === "hisob"}
                  label={copy.balance}
                />
              )}
              <ThemeToggle compact={collapsed} vertical={collapsed} />
              {!collapsed && <LanguagePicker />}
            </>
          )}
        />
      </div>

      <header className="app-topbar">
        <Link href="/projects" className="app-brand">
          Nashr
        </Link>
        <nav className="app-topbar-links">
          {navigation.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              data-active={item.key === active ? "true" : undefined}
            >
              {item.label}
            </Link>
          ))}
          {balance !== null && (
            <Link
              href="/hisob"
              data-active={active === "hisob" ? "true" : undefined}
              // whitespace-nowrap + shrink-0: the topbar is a flex row, and a
              // three-word amount ("35 000 so'm") otherwise wraps onto three
              // lines at 390px and doubles the bar's height.
              className="flex shrink-0 items-center gap-1.5 whitespace-nowrap"
              title={`${copy.balance}: ${soum(balance)}`}
            >
              <Wallet size={15} strokeWidth={1.75} aria-hidden />
              <span className="data-text whitespace-nowrap">
                {soum(balance)}
              </span>
            </Link>
          )}
          <ThemeToggle compact />
          <LanguagePicker />
          <button type="button" onClick={signOut}>
            {copy.signOut}
          </button>
        </nav>
      </header>

      <main className="app-panel">{children}</main>
    </div>
  );
}
