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
//
// Coherence round, four gaps:
//
//   G12/G33 — the read was `.then`-only, so an unreachable backend rendered
//             the loading skeleton forever and the raw PostgREST sentence was
//             the error copy. Now: a timeout, a catch, and three states a
//             person can tell apart — loading / empty / unreachable-with-retry.
//             The "Yangi" CTA survives the error state: a user whose list
//             failed to load can still start new work.
//   G25     — rows carried a chip with no step and no elapsed time. ONE
//             Realtime channel for the whole list (never one per row, never a
//             per-row poll) keeps the generating rows honest about which step
//             they are on.
//   G41     — the empty folio offered a search box and a view toggle over zero
//             rows. Both are suppressed until there is something to search.

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, ChevronsUpDown, LayoutGrid, List, Plus } from "lucide-react";
import type { RealtimeChannel } from "@supabase/supabase-js";
import { AppChrome } from "@/components/chrome";
import { FilterChips, SearchList, type SearchResult } from "@/components/bui";
import { Button, DataText, EmptyState, Skeleton, StatusBadge } from "@/components/ui";
import { describeError } from "@/lib/errors";
import {
  applyJob,
  chipOf,
  elapsedLabel,
  isTerminalJob,
  jobSnapshot,
  liveStatusOf,
  newestByProject,
  stepLabelOf,
  supabaseFailure,
  type JobSnapshot,
} from "@/lib/folio";
import { useAppSession } from "@/lib/use-session";
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

/** No read may hang forever — that is exactly how the eternal skeleton happens. */
const READ_TIMEOUT_MS = 15_000;
/** Safety net behind Realtime, list-wide. Only runs while something is live. */
const JOB_REFRESH_MS = 20_000;
/** How often the elapsed counters re-render while a run is in flight. */
const TICK_MS = 15_000;

const TYPE_LABEL: Record<string, string> = {
  presentation: "Taqdimot",
  article: "Maqola",
};

// One chip per lifecycle stage a user actually thinks in, not one per status:
// draft / sourcing / interview all mean "not generating yet". The status → chip
// mapping itself lives in lib/folio.ts, shared with the row badge so the two
// can never disagree.
const CHIPS: ReadonlyArray<{ key: string; label: string; dot: string }> = [
  { key: "draft", label: "Qoralama", dot: "var(--orange)" },
  { key: "generating", label: "Yaratilmoqda", dot: "var(--accent)" },
  { key: "ready", label: "Tayyor", dot: "var(--green)" },
  { key: "failed", label: "Xatolik", dot: "var(--red)" },
  { key: "archived", label: "Arxiv", dot: "var(--ink-3)" },
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

/** The status cell: the badge, plus what the run is doing if one is live. */
function LiveStatus({
  status,
  job,
  now,
}: {
  status: string;
  job: JobSnapshot | null;
  now: number;
}) {
  const step = stepLabelOf(job);
  const elapsed = elapsedLabel(job, now);
  return (
    <span className="projects-live">
      <StatusBadge status={status} />
      {(step ?? elapsed) !== null && (
        <span className="projects-live-meta">
          {step !== null && (
            <span className="projects-step" title={step}>
              {step}
            </span>
          )}
          {elapsed !== null && <DataText className="projects-elapsed">{elapsed}</DataText>}
        </span>
      )}
    </span>
  );
}

/**
 * The unreachable state. Never `ErrorState`: this one must carry the machine
 * text into a collapsible detail instead of onto the page (§4 of the audit),
 * and it is what makes "down" look different from "loading".
 */
function FolioError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const friendly = describeError(error);
  return (
    <div className="projects-fail" data-tone={friendly.tone} role="alert">
      <p className="projects-fail-title">{friendly.title}</p>
      <p className="projects-fail-message">{friendly.message}</p>
      <p className="projects-fail-note">
        Ro‘yxat yuklanmadi — lekin yangi loyihani hozir ham boshlashingiz mumkin.
      </p>
      <div className="projects-fail-actions">
        <Button variant="ghost" onClick={onRetry}>
          {friendly.action?.label ?? "Qayta urinish"}
        </Button>
      </div>
      {friendly.detail !== undefined && (
        <details className="projects-detail">
          <summary>Texnik tafsilot</summary>
          <code>{friendly.detail}</code>
        </details>
      )}
    </div>
  );
}

export default function ProjectsPage() {
  const router = useRouter();
  const { session } = useAppSession();
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [jobs, setJobs] = useState<Record<string, JobSnapshot>>({});
  const [now, setNow] = useState(() => Date.now());

  const [query, setQuery] = useState("");
  const [active, setActive] = useState("all");
  const [view, setView] = useState<ViewMode>("list");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortAsc, setSortAsc] = useState(false);

  // Read by the Realtime handler without making the channel depend on state
  // that changes on every load — a re-subscribe per refresh would be a leak.
  const jobsRef = useRef<Record<string, JobSnapshot>>({});
  jobsRef.current = jobs;
  const knownIds = useRef<ReadonlySet<string>>(new Set());

  const loadProjects = useCallback(async (token: string): Promise<void> => {
    try {
      const supabase = createRlsClient(token);
      const {
        data,
        error,
        status,
      } = await supabase
        .from("projects")
        .select("id,title,type,status,created_at")
        .order("created_at", { ascending: false })
        .abortSignal(AbortSignal.timeout(READ_TIMEOUT_MS));
      // supabase-js RESOLVES on a dead network (status 0, data null); the
      // envelope is the failure path, not the rejection.
      if (error) {
        setLoadError(supabaseFailure(error, status));
        return;
      }
      setProjects((data ?? []) as ProjectRow[]);
      setLoadError(null);
    } catch (thrown) {
      setLoadError(thrown);
    }
  }, []);

  /**
   * Live rows. Only the ACTIVE jobs: everything terminal is already carried by
   * the projects row, and reconstructing history here would be a second, and
   * disagreeing, source of truth. Failures are silent by design — the list is
   * the surface, live status is an enhancement on top of it.
   */
  const loadJobs = useCallback(
    async (token: string): Promise<void> => {
      try {
        const supabase = createRlsClient(token);
        const { data, error } = await supabase
          .from("generation_jobs")
          .select("id,project_id,status,progress,created_at,started_at")
          .in("status", ["queued", "processing"])
          .order("created_at", { ascending: false })
          .abortSignal(AbortSignal.timeout(READ_TIMEOUT_MS));
        if (error || !data) return;
        const next = newestByProject(data);
        // A run that ended between two reads leaves the projects row stale, so
        // the database — not a guess here — says what the project became.
        const ended = Object.keys(jobsRef.current).some((id) => !(id in next));
        setJobs(next);
        if (ended) void loadProjects(token);
      } catch {
        // See above: never let the live layer take the list down with it.
      }
    },
    [loadProjects],
  );

  useEffect(() => {
    if (!session) return;
    const token = session.accessToken;
    void loadProjects(token);
    void loadJobs(token);
  }, [session, loadProjects, loadJobs]);

  // ONE channel for the whole folio, filtered to this user's jobs. Never one
  // per row: a folio of thirty projects would otherwise open thirty sockets.
  useEffect(() => {
    if (!session) return;
    const token = session.accessToken;
    let channel: RealtimeChannel | null = null;
    try {
      const supabase = createRlsClient(token);
      channel = supabase
        .channel(`folio:${session.userId}`)
        .on(
          "postgres_changes",
          {
            event: "*",
            schema: "public",
            table: "generation_jobs",
            filter: `user_id=eq.${session.userId}`,
          },
          (payload) => {
            const snapshot = jobSnapshot(payload.new);
            if (!snapshot) return;
            setJobs((current) => applyJob(current, snapshot));
            // A run that just ended, or one for a project this tab has never
            // seen, both mean the list itself is out of date.
            if (isTerminalJob(snapshot.status) || !knownIds.current.has(snapshot.projectId)) {
              void loadProjects(token);
            }
          },
        )
        .subscribe();
    } catch {
      // Realtime is an optimisation; the interval below is the safety net.
    }
    return () => {
      if (channel) void channel.unsubscribe();
    };
  }, [session, loadProjects]);

  const live = Object.keys(jobs).length > 0;

  useEffect(() => {
    if (!live) return;
    const tick = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(tick);
  }, [live]);

  useEffect(() => {
    if (!live || !session) return;
    const token = session.accessToken;
    const timer = window.setInterval(() => void loadJobs(token), JOB_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [live, session, loadJobs]);

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

  const retry = useCallback(() => {
    if (!session) return;
    setLoadError(null);
    setProjects(null);
    void loadProjects(session.accessToken);
    void loadJobs(session.accessToken);
  }, [session, loadProjects, loadJobs]);

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

  useEffect(() => {
    knownIds.current = new Set((projects ?? []).map((row) => row.id));
  }, [projects]);

  // One derivation for the badge AND the chips: a row can never sit under
  // "Qoralama" while its own badge reads "Yaratilmoqda".
  const statusOf = useCallback(
    (row: ProjectRow) => liveStatusOf(row.status, jobs[row.id] ?? null),
    [jobs],
  );

  const needle = query.trim().toLowerCase();
  const searched = useMemo(
    () => (needle === "" ? rows : rows.filter((row) => row.title.toLowerCase().includes(needle))),
    [rows, needle],
  );
  const visible = useMemo(
    () =>
      active === "all" ? searched : searched.filter((row) => chipOf(statusOf(row)) === active),
    [searched, active, statusOf],
  );
  const shownIds = useMemo(() => new Set(visible.map((row) => row.id)), [visible]);

  // Counts follow the query: with a term typed, a chip promises exactly what
  // clicking it will reveal.
  const chips = useMemo(() => {
    const present = new Set((projects ?? []).map((row) => chipOf(statusOf(row))));
    return [
      { key: "all", label: "Hammasi", count: searched.length },
      ...CHIPS.filter((chip) => chip.key !== "archived" || present.has("archived")).map((chip) => ({
        key: chip.key,
        label: chip.label,
        dot: chip.dot,
        count: searched.filter((row) => chipOf(statusOf(row)) === chip.key).length,
      })),
    ];
  }, [projects, searched, statusOf]);

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
  const failed = loadError !== null;
  const hasRows = projects !== null && projects.length > 0;
  const blank = projects !== null && projects.length === 0 && !failed;
  const loading = projects === null && !failed;

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
          <div className="projects-controls">
            {/* Nothing to search and nothing to lay out until rows exist (G41). */}
            {hasRows && (
              <>
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
              </>
            )}

            {/* Kept in the failure state on purpose: a broken read must not
                strand a user who only wants to start something new. */}
            {(hasRows || failed) && (
              <Link href="/new" className="btn btn-primary projects-new">
                <span className="btn-label">
                  <Plus size={16} strokeWidth={2} aria-hidden />
                  Yangi
                </span>
              </Link>
            )}
          </div>
        </header>

        {failed && <FolioError error={loadError} onRetry={retry} />}

        {loading && (
          <div className="projects-loading">
            <p className="projects-loading-note">Loyihalar yuklanmoqda…</p>
            <Skeleton lines={5} />
          </div>
        )}

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

        {hasRows && (
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
                            <LiveStatus
                              status={statusOf(row)}
                              job={jobs[row.id] ?? null}
                              now={now}
                            />
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
                        <LiveStatus status={statusOf(row)} job={jobs[row.id] ?? null} now={now} />
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
