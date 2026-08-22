"use client";

import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, LogOut, PanelLeft, Search, X } from "lucide-react";
import GlideMenu from "@/components/bui/glide-menu";

// Ported from beautifului.dev "sidebar-nav" (MIT). Kept: SIDEBAR_MOTION /
// CHAT_SEARCH_MOTION, the collapse choreography and sidebar-copy fade,
// GlideGroup + RailButton, the portal workspace menu with outside-click close,
// the searchable recents with Escape/clear and the empty line, the footer slot.
// Replaced: @central-icons-react -> lucide-react, the WORKSPACE / NAV_ITEMS /
// DEFAULT_RECENTS fixtures -> props, and the demo rows -> next/link.

/* ─────────────────────────────────────────────────────────
 * SIDEBAR NAV
 * Shared by the design-system preview and the harness shell:
 * compact workspace switcher, primary navigation, searchable
 * chat history, and a collapse that preserves icon alignment.
 * ───────────────────────────────────────────────────────── */

export type SidebarRecent = {
  id: string;
  label: string;
  href: string;
};

export type SidebarNavItem = {
  key: string;
  label: string;
  href: string;
  icon: ReactNode;
};

type SidebarNavProps = {
  brand: { name: string };
  nav: ReadonlyArray<SidebarNavItem>;
  activeNav?: string;
  recents: ReadonlyArray<SidebarRecent>;
  recentsTitle?: string;
  onSignOut: () => void;
  /** Rendered in the pinned footer; told whether the rail is collapsed. */
  footer?: (collapsed: boolean) => ReactNode;
  className?: string;
};

const SIDEBAR_MOTION = {
  expandedWidth: 224,
  collapsedWidth: 52,
  duration: 280,
  copyDuration: 180,
  copyOffset: 8,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
};

/* ─────────────────────────────────────────────────────────
 * CHAT SEARCH STORYBOARD
 *
 *   0ms   search is triggered; Chats label begins fading
 *   0ms   field grows right → left from the search control
 * 180ms   field fills the row; cursor is focused and ready
 * ───────────────────────────────────────────────────────── */
const CHAT_SEARCH_MOTION = {
  duration: 180,
  closedWidth: 28,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
};

const ROW_CLASS =
  "sidebar-row relative z-10 mx-2 flex h-8 items-center rounded-[8px] px-2 text-left transition-[width,background-color,color,transform] duration-150 active:scale-[0.98]";

function GlideGroup({ children }: { children: ReactNode }) {
  return (
    <GlideMenu
      rowSelector="[data-row]"
      highlightClassName="sidebar-glide-highlight rounded-[7px] bg-hover-2"
      className="group/glide flex flex-col gap-px"
    >
      {children}
    </GlideMenu>
  );
}

function RailLink({
  icon,
  label,
  href,
  active = false,
}: {
  icon: ReactNode;
  label: string;
  href: string;
  active?: boolean;
}) {
  return (
    <Link
      data-row
      href={href}
      title={label}
      className={`${ROW_CLASS} no-underline hover:no-underline ${
        active ? "bg-hover-2 group-hover/glide:bg-transparent" : ""
      }`}
    >
      <span
        className={`flex size-5 shrink-0 items-center justify-center ${
          active ? "text-ink" : "text-ink-2"
        }`}
      >
        {icon}
      </span>
      <span
        className={`sidebar-copy ml-1.5 min-w-0 flex-1 truncate text-[14px] font-medium ${
          active ? "text-ink" : "text-ink-2"
        }`}
      >
        {label}
      </span>
    </Link>
  );
}

function WorkspaceMenu({
  brand,
  position,
  onClose,
  onSignOut,
}: {
  brand: { name: string };
  position: { top: number; left: number };
  onClose: () => void;
  onSignOut: () => void;
}) {
  return createPortal(
    <div
      data-workspace-menu
      className="fixed z-50 w-64 rounded-[14px] bg-surface p-1.5 shadow-overlay"
      style={{
        top: position.top,
        left: position.left,
        animation: "pop-in 180ms cubic-bezier(0.23,1,0.32,1) both",
        transformOrigin: "top left",
      }}
    >
      <GlideMenu
        className="flex flex-col gap-px"
        highlightClassName="inset-x-0 rounded-[8px] bg-hover-2"
      >
        <button
          data-menu-row
          type="button"
          onClick={onClose}
          className="relative z-10 flex h-10 w-full items-center gap-1.5 rounded-[8px] px-2 text-left"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-[7px] bg-ink text-[11px] font-semibold text-surface">
            {brand.name.slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink">
            {brand.name}
          </span>
          <span className="shrink-0 text-ink">
            <Check size={16} strokeWidth={2} aria-hidden />
          </span>
        </button>
        <div className="my-1 h-px bg-line" />
        <button
          data-menu-row
          type="button"
          onClick={() => {
            onClose();
            onSignOut();
          }}
          className="relative z-10 flex h-9 w-full items-center gap-1.5 rounded-[8px] px-2 text-left"
        >
          <span className="flex size-5 shrink-0 items-center justify-center text-ink-2">
            <LogOut size={16} strokeWidth={1.75} aria-hidden />
          </span>
          <span className="min-w-0 flex-1 truncate text-[13.5px] text-ink">Chiqish</span>
        </button>
      </GlideMenu>
    </div>,
    document.body,
  );
}

export default function SidebarNav({
  brand,
  nav,
  activeNav,
  recents,
  recentsTitle = "Oxirgi loyihalar",
  onSignOut,
  footer,
  className = "",
}: SidebarNavProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [workspacePosition, setWorkspacePosition] = useState({ top: 0, left: 0 });
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const workspaceButtonRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const visibleRecents = recents.filter((item) =>
    item.label.toLowerCase().includes(query.trim().toLowerCase()),
  );

  useEffect(() => {
    if (!workspaceOpen) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Element;
      if (!target.closest("[data-workspace-trigger]") && !target.closest("[data-workspace-menu]")) {
        setWorkspaceOpen(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [workspaceOpen]);

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  const collapse = () => {
    setCollapsed(true);
    setWorkspaceOpen(false);
    setSearchOpen(false);
    setQuery("");
  };

  return (
    <aside
      data-sidebar-collapsed={collapsed}
      aria-label="Ish maydoni navigatsiyasi"
      className={`relative flex h-full shrink-0 overflow-hidden transition-[width] ${className}`}
      style={
        {
          width: collapsed ? SIDEBAR_MOTION.collapsedWidth : SIDEBAR_MOTION.expandedWidth,
          transitionDuration: `${SIDEBAR_MOTION.duration}ms`,
          transitionTimingFunction: SIDEBAR_MOTION.easing,
          "--sidebar-copy-duration": `${SIDEBAR_MOTION.copyDuration}ms`,
          "--sidebar-copy-offset": `${SIDEBAR_MOTION.copyOffset}px`,
          "--sidebar-easing": SIDEBAR_MOTION.easing,
        } as CSSProperties
      }
    >
      <div className="flex min-h-0 w-[224px] shrink-0 flex-col pb-2">
        <div className="relative mb-2.5 h-10 shrink-0">
          <button
            ref={workspaceButtonRef}
            data-workspace-trigger
            type="button"
            aria-expanded={workspaceOpen}
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
            onClick={() => {
              if (!workspaceOpen && workspaceButtonRef.current) {
                const rect = workspaceButtonRef.current.getBoundingClientRect();
                setWorkspacePosition({ top: rect.bottom + 6, left: rect.left });
              }
              setWorkspaceOpen((open) => !open);
            }}
            className="sidebar-workspace-control absolute left-2 top-1 flex h-8 w-[164px] items-center rounded-[8px] px-2 text-left transition-[background-color,transform] duration-100 hover:bg-hover-2 active:scale-[0.99]"
          >
            <span className="sidebar-logo flex size-5 shrink-0 items-center justify-center rounded-[6px] bg-ink font-display text-[11px] font-bold text-surface">
              {brand.name.slice(0, 1)}
            </span>
            <span className="sidebar-copy ml-1.5 min-w-0 flex-1 truncate font-display text-[15px] font-bold tracking-[-0.01em] text-ink">
              {brand.name}
            </span>
            <span className="sidebar-copy ml-1 flex shrink-0 text-ink-3">
              <ChevronDown size={15} strokeWidth={1.75} aria-hidden />
            </span>
          </button>

          {workspaceOpen && (
            <WorkspaceMenu
              brand={brand}
              position={workspacePosition}
              onClose={() => setWorkspaceOpen(false)}
              onSignOut={onSignOut}
            />
          )}

          <button
            type="button"
            aria-label="Panelni yig‘ish"
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
            onClick={collapse}
            className="sidebar-collapse-control absolute right-2 top-1 flex size-8 items-center justify-center rounded-[8px] text-ink-3 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <PanelLeft size={17} strokeWidth={1.75} aria-hidden />
          </button>
          <button
            type="button"
            aria-label="Panelni ochish"
            aria-hidden={!collapsed}
            tabIndex={collapsed ? 0 : -1}
            onClick={() => setCollapsed(false)}
            className="sidebar-expand-control absolute left-2 top-0.5 flex size-9 items-center justify-center rounded-[8px] text-ink-3 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <PanelLeft size={17} strokeWidth={1.75} className="rotate-180" aria-hidden />
          </button>
        </div>

        <GlideGroup>
          {nav.map((item) => (
            <RailLink
              key={item.key}
              icon={item.icon}
              label={item.label}
              href={item.href}
              active={activeNav === item.key}
            />
          ))}
        </GlideGroup>

        <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
          <div className="sidebar-copy relative mx-2 mb-1 h-8">
            <div
              aria-hidden={searchOpen}
              className={`absolute inset-0 flex items-center gap-1.5 px-2 text-[12.5px] font-medium text-ink-3 transition-[opacity,transform] ${
                searchOpen ? "pointer-events-none -translate-x-1 opacity-0" : "translate-x-0 opacity-100"
              }`}
              style={{
                transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`,
                transitionTimingFunction: CHAT_SEARCH_MOTION.easing,
              }}
            >
              <span className="truncate">{recentsTitle}</span>
            </div>

            <button
              type="button"
              aria-label="Loyihalarni qidirish"
              aria-expanded={searchOpen}
              onClick={() => setSearchOpen(true)}
              className={`absolute right-0 top-0 z-10 flex size-8 items-center justify-center rounded-[8px] text-ink-3 transition-[opacity,background-color,color,transform] hover:bg-hover-2 hover:text-ink active:scale-[0.96] ${
                searchOpen ? "pointer-events-none opacity-0" : "opacity-100"
              }`}
              style={{ transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms` }}
            >
              <Search size={15} strokeWidth={1.75} aria-hidden />
            </button>

            <div
              className={`absolute right-0 top-0 z-20 flex h-8 items-center overflow-hidden rounded-[8px] bg-field text-ink-3 shadow-hairline transition-[width,opacity] focus-within:text-ink-2 ${
                searchOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
              }`}
              style={{
                width: searchOpen ? "100%" : CHAT_SEARCH_MOTION.closedWidth,
                transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`,
                transitionTimingFunction: CHAT_SEARCH_MOTION.easing,
              }}
            >
              <span className="ml-2 flex shrink-0 items-center justify-center">
                <Search size={14} strokeWidth={1.75} aria-hidden />
              </span>
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setSearchOpen(false);
                    setQuery("");
                  }
                }}
                placeholder="Loyiha qidirish"
                aria-label="Loyihalar tarixidan qidirish"
                className="ml-1.5 min-w-0 flex-1 bg-transparent text-[13px] font-medium text-ink outline-none placeholder:text-ink-3"
              />
              <button
                type="button"
                aria-label="Qidiruvni yopish"
                onClick={() => {
                  setSearchOpen(false);
                  setQuery("");
                }}
                className="flex size-8 shrink-0 items-center justify-center rounded-[8px] text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover-2 hover:text-ink active:scale-[0.96]"
              >
                <X size={15} strokeWidth={1.75} aria-hidden />
              </button>
            </div>
          </div>

          <GlideGroup>
            {visibleRecents.map((item) => (
              <Link
                key={item.id}
                data-row
                href={item.href}
                title={item.label}
                className={`${ROW_CLASS} no-underline hover:no-underline`}
              >
                <span className="sidebar-copy min-w-0 flex-1 truncate text-[14px] font-medium text-ink-2">
                  {item.label}
                </span>
              </Link>
            ))}
            {query && visibleRecents.length === 0 && (
              <div className="sidebar-copy mx-2 px-2 py-2 text-[12.5px] text-ink-3">
                Loyiha topilmadi
              </div>
            )}
          </GlideGroup>
        </div>

        {footer && (
          <div
            className={`mt-3 border-t border-line pt-3 ${
              collapsed ? "mx-1.5 w-[40px]" : "mx-2 w-[208px]"
            }`}
          >
            {footer(collapsed)}
          </div>
        )}
      </div>
    </aside>
  );
}
