"use client";

// The authed shell: proves the whole identity chain end to end — app JWT →
// Supabase RLS read of the user's own projects. This page IS the P1 gate's
// positive half; the negative half (cannot read another user's rows) is the
// two-account test in the gate script.
//
// Shape is the Prism workspace surface: one header line (title · search ·
// view toggle · New), status chips under it, then the list. Ported pieces:
// SearchList (#15) drives the header field and its results dropdown;
// FilterChips (#13) is imported verbatim; the table below reuses
// filter-table's collapsing-row grammar because rows here must be links.

import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, ChevronsUpDown, LayoutGrid, List, Plus } from "lucide-react";
import { AppChrome } from "@/components/chrome";
import { FilterChips, SearchList, type SearchResult } from "@/components/bui";
import { DataText, EmptyState, ErrorState, Skeleton, StatusBadge } from "@/components/ui";
import { type AppSession, loadSession } from "@/lib/session";
import { createRlsClient } from "@/lib/supabase";
import "./projects.css";

interface ProjectRow {
  id: string;
  title: string;
  type: string;
  status: string;
  created_at: string | null;
}

type ViewMode = "list" | "grid";
type SortKey = "name" | "date";

const VIEW_KEY = "nashr.projects.view";

const TYPE_LABEL: Record<string, string> = {
  presentation: "Taqdimot",
  article: "Maqola",
};

// One chip per lifecycle stage a user actually thinks in, not one per status:
// draft / sourcing / interview all mean "not generating yet".
const CHIPS: ReadonlyArray<{
  key: string;
  label: string;
  dot: string;
  statuses: ReadonlyArray<string>;
}> = [
  {
    key: "draft",
    label: "Qoralama",
    dot: "var(--orange)",
    statuses: ["draft", "sourcing", "interview"],
  },
  { key: "generating", label: "Yaratilmoqda", dot: "var(--accent)", statuses: ["generating"] },
  { key: "ready", label: "Tayyor", dot: "var(--green)", statuses: ["ready"] },
  { key: "failed", label: "Xatolik", dot: "var(--red)", statuses: ["failed"] },
  { key: "archived", label: "Arxiv", dot: "var(--ink-3)", statuses: ["archived"] },
];

// dd.mm.yyyy — a filing date, not a "3 days ago" that ages behind the user's
// back. Tabular figures keep the column edge straight down the list.
function filedOn(value: string | null): string {
  if (!value) return "—";
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return "—";
  const pad = (part: number) => part.toString().padStart(2, "0");
  return `${pad(when.getDate())}.${pad(when.getMonth() + 1)}.${when.getFullYear()}`;
}

function chipOf(status: string): string {
  return CHIPS.find((chip) => chip.statuses.includes(status))?.key ?? "other";
}

function SortHead({
  label,
  on,
  asc,
  onClick,
}: {
  label: string;
  on: boolean;
  asc: boolean;
  onClick: () => void;
}) {
  const Glyph = on ? (asc ? ArrowUp : ArrowDown) : ChevronsUpDown;
  return (
    <button
      type="button"
      className="projects-sort"
      data-active={on ? "true" : undefined}
      aria-label={`${label} bo‘yicha saralash`}
      onClick={onClick}
    >
      {label}
      <Glyph size={12} strokeWidth={1.75} aria-hidden />
    </button>
  );
}

export default function ProjectsPage() {
  const router = useRouter();
  const [session, setSession] = useState<AppSession | null>(null);
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [active, setActive] = useState("all");
  const [view, setView] = useState<ViewMode>("list");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortAsc, setSortAsc] = useState(false);

  const refresh = useCallback((activeSession: AppSession) => {
    setError(null);
    const supabase = createRlsClient(activeSession.accessToken);
    supabase
      .from("projects")
      .select("id,title,type,status,created_at")
      .order("created_at", { ascending: false })
      .then(({ data, error: queryError }) => {
        if (queryError) {
          setError(queryError.message);
        } else {
          setProjects((data ?? []) as ProjectRow[]);
        }
      });
  }, []);

  useEffect(() => {
    const current = loadSession();
    if (!current) {
      router.replace("/login?returnTo=" + encodeURIComponent("/projects"));
      return;
    }
    setSession(current);
    refresh(current);
  }, [router, refresh]);

  // Read after mount, never as a lazy initialiser: the server renders "list"
  // and a differing first client render would be a hydration mismatch.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(VIEW_KEY);
      if (stored === "grid" || stored === "list") setView(stored);
    } catch {
      // Storage denial just means the default view for this session.
    }
  }, []);

  const pickView = useCallback((next: ViewMode) => {
    setView(next);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      // See above.
    }
  }, []);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortAsc((value) => !value);
      return;
    }
    setSortKey(key);
    setSortAsc(key === "name");
  }

  const rows = useMemo(() => {
    const list = [...(projects ?? [])];
    list.sort((a, b) => {
      const delta =
        sortKey === "name"
          ? a.title.localeCompare(b.title, "uz")
          : (a.created_at ?? "").localeCompare(b.created_at ?? "");
      return sortAsc ? delta : -delta;
    });
    return list;
  }, [projects, sortKey, sortAsc]);

  const needle = query.trim().toLowerCase();
  const searched = useMemo(
    () => (needle === "" ? rows : rows.filter((row) => row.title.toLowerCase().includes(needle))),
    [rows, needle],
  );
  const visible = useMemo(
    () => (active === "all" ? searched : searched.filter((row) => chipOf(row.status) === active)),
    [searched, active],
  );
  const shownIds = useMemo(() => new Set(visible.map((row) => row.id)), [visible]);

  // Counts follow the query: with a term typed, a chip promises exactly what
  // clicking it will reveal.
  const chips = useMemo(() => {
    const present = new Set((projects ?? []).map((row) => chipOf(row.status)));
    return [
      { key: "all", label: "Hammasi", count: searched.length },
      ...CHIPS.filter((chip) => chip.key !== "archived" || present.has("archived")).map((chip) => ({
        key: chip.key,
        label: chip.label,
        dot: chip.dot,
        count: searched.filter((row) => chipOf(row.status) === chip.key).length,
      })),
    ];
  }, [projects, searched]);

  const results: SearchResult[] = useMemo(
    () =>
      visible.slice(0, 6).map((row) => ({
        key: row.id,
        label: row.title,
        meta: filedOn(row.created_at),
      })),
    [visible],
  );

  const open = needle !== "";
  const blank = projects !== null && projects.length === 0 && !error;

  function onSearchKeys(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      setQuery("");
      return;
    }
    if (event.key !== "Enter") return;
    const first = results[0];
    if (!first) return;
    event.preventDefault();
    router.push(`/projects/${first.key}`);
  }

  return (
    <AppChrome active="projects">
      <div className="projects">
        <header className="projects-head">
          <h1 className="projects-title">Loyihalar</h1>
          {projects !== null && !error && (
            <div className="projects-controls">
              <div
                className="projects-search"
                data-open={open ? "true" : "false"}
                onKeyDown={onSearchKeys}
              >
                <SearchList
                  query={query}
                  onQueryChange={setQuery}
                  placeholder="Loyiha qidirish"
                  results={results}
                  onPick={(item) => router.push(`/projects/${item.key}`)}
                  emptyTitle="Mos loyiha topilmadi"
                  emptyHint="Boshqa so‘z bilan urinib ko‘ring"
                />
              </div>

              <div className="projects-view" role="group" aria-label="Ko‘rinish">
                <button
                  type="button"
                  aria-pressed={view === "list"}
                  aria-label="Ro‘yxat"
                  onClick={() => pickView("list")}
                >
                  <List size={16} strokeWidth={1.75} aria-hidden />
                </button>
                <button
                  type="button"
                  aria-pressed={view === "grid"}
                  aria-label="Katakcha"
                  onClick={() => pickView("grid")}
                >
                  <LayoutGrid size={16} strokeWidth={1.75} aria-hidden />
                </button>
              </div>

              {!blank && (
                <Link href="/new" className="btn btn-primary projects-new">
                  <span className="btn-label">
                    <Plus size={16} strokeWidth={2} aria-hidden />
                    Yangi
                  </span>
                </Link>
              )}
            </div>
          )}
        </header>

        {error && (
          <ErrorState message={error} onRetry={session ? () => refresh(session) : undefined} />
        )}

        {projects === null && !error && <Skeleton lines={5} />}

        {blank && (
          <div className="projects-empty">
            <EmptyState
              title="Hozircha loyiha yo‘q"
              hint="Manba yuklang, talabni ayting — taqdimot shu yerda paydo bo‘ladi."
            >
              <Link href="/new" className="btn btn-primary projects-new">
                <span className="btn-label">
                  <Plus size={16} strokeWidth={2} aria-hidden />
                  Birinchi loyiha
                </span>
              </Link>
            </EmptyState>
          </div>
        )}

        {projects !== null && projects.length > 0 && !error && (
          <>
            <div className="projects-chips">
              <FilterChips filters={chips} active={active} onChange={setActive} />
            </div>

            {view === "list" ? (
              <div className="projects-table" role="region" aria-label="Loyihalar jadvali">
                <div
                  className="grid border-b border-line px-4 py-2 text-[11.5px] font-medium text-ink-3"
                  style={{ gridTemplateColumns: "var(--cols)" }}
                >
                  <span>
                    <SortHead
                      label="Nomi"
                      on={sortKey === "name"}
                      asc={sortAsc}
                      onClick={() => toggleSort("name")}
                    />
                  </span>
                  <span className="projects-cell-type">Turi</span>
                  <span>
                    <SortHead
                      label="Yaratilgan"
                      on={sortKey === "date"}
                      asc={sortAsc}
                      onClick={() => toggleSort("date")}
                    />
                  </span>
                  <span>Holat</span>
                </div>

                {rows.map((row) => {
                  const shown = shownIds.has(row.id);
                  return (
                    <div
                      key={row.id}
                      className="grid transition-[grid-template-rows,opacity] duration-300"
                      style={{
                        gridTemplateRows: shown ? "1fr" : "0fr",
                        opacity: shown ? 1 : 0,
                        transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
                      }}
                    >
                      <div className="overflow-hidden">
                        <Link
                          href={`/projects/${row.id}`}
                          tabIndex={shown ? undefined : -1}
                          aria-hidden={shown ? undefined : true}
                          className="grid items-center border-b border-line px-4 py-2.5 text-[12px]
                            transition-colors duration-100 hover:bg-hover hover:no-underline"
                          style={{ gridTemplateColumns: "var(--cols)" }}
                        >
                          <span className="projects-cell-title min-w-0 truncate pr-4">
                            {row.title}
                          </span>
                          <span className="projects-cell-type min-w-0 truncate text-ink-2">
                            {TYPE_LABEL[row.type] ?? row.type}
                          </span>
                          <span className="min-w-0 text-ink-3">
                            <DataText>{filedOn(row.created_at)}</DataText>
                          </span>
                          <span className="min-w-0">
                            <StatusBadge status={row.status} />
                          </span>
                        </Link>
                      </div>
                    </div>
                  );
                })}

                {visible.length === 0 && <p className="projects-none">Mos loyiha topilmadi</p>}
              </div>
            ) : (
              <>
                <div className="projects-grid">
                  {visible.map((row, index) => (
                    <Link
                      key={row.id}
                      href={`/projects/${row.id}`}
                      className="projects-card"
                      style={{
                        animation: `fade-up 320ms cubic-bezier(0.23,1,0.32,1) ${index * 40}ms both`,
                      }}
                    >
                      <span className="projects-card-title">{row.title}</span>
                      <span className="projects-card-foot">
                        <span>{TYPE_LABEL[row.type] ?? row.type}</span>
                        <DataText>{filedOn(row.created_at)}</DataText>
                        <StatusBadge status={row.status} />
                      </span>
                    </Link>
                  ))}
                </div>
                {visible.length === 0 && <p className="projects-none">Mos loyiha topilmadi</p>}
              </>
            )}

            <p className="projects-count">
              <DataText>{visible.length}</DataText> ta loyiha
            </p>
          </>
        )}
      </div>
    </AppChrome>
  );
}
