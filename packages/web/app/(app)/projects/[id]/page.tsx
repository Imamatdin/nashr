"use client";

// The project workspace, rebuilt on truth.
//
// What it was: a single scrolling column that derived everything from the
// `?job=` URL param. A returning user — anyone arriving from the folio or the
// sidebar — saw the idle "Taqdimot yaratish · 10 000 so'm" pitch over a project
// that might be mid-run, already failed, or already delivered. On failed and
// ready projects that click was a real second charge, and on a ready one it
// overwrote the only deck row (G3, G5). The deck itself sat in a fixed-height
// iframe below ~700px of upload form and the pay-again block (G18), with no way
// to say what to change (G4) even though the whole edit engine shipped
// bot-side.
//
// What it is now: state from PROJECT + LATEST JOB (lib/workspace-state.ts), and
// a split view — conversation on the left, artifact on the right, tabs below
// 1024px. The conversation IS the spine: "fix slide 3" is a message, and a
// deck-wide instruction is just another message (the Gamma agent-edit pattern),
// so there is no edit mode to get into or out of.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AppChrome } from "@/components/chrome";
import { ArticleWorkspace } from "@/components/article-workspace";
import { EvidenceMap } from "@/components/evidence-graph";
import { useLocale } from "@/components/locale-provider";
import { PresentationDesigner } from "@/components/presentation-designer";
import { ResearchPanel } from "@/components/research-panel";
import {
  WORKSPACE_COPY,
  type WorkspaceCopy,
} from "@/components/workspace-copy";
import {
  ChatThread,
  ContextCards,
  LoadingState,
  StreamingText,
  TaskRows,
  ThinkingState,
  type ChatThreadMessage,
  type ContextChunk,
  type TaskRow,
} from "@/components/bui";
import {
  Button,
  DataText,
  EmptyState,
  ErrorState,
  FileField,
  StatusBadge,
  Toast,
} from "@/components/ui";
import { stepStates } from "@/lib/steps";
import { soum, tierOf } from "@/lib/packages";
import {
  ApiError,
  type ChatHistoryView,
  type DeckAccessView,
  type DecisionsView,
  type PricingView,
  type ProvenanceRow,
  type ProvenanceView,
  approvePending,
  decisionOf,
  enqueueJob,
  getChat,
  getDecisions,
  getDeckAccess,
  getPricing,
  getProvenance,
  manageShare,
  postChat,
  presignUpload,
  registerSource,
  rejectPending,
  uploadToR2,
} from "@/lib/api";
import {
  creditCopy,
  describeError,
  describeJobFailure,
  rateLimitCopy,
  reasonOf,
} from "@/lib/errors";
import {
  backgroundLabel,
  decidedFor,
  hasArgument,
  moodLabel,
  phaseLabel,
  swatches,
} from "@/lib/decisions";
import { useAppSession } from "@/lib/use-session";
import { useLiveJob } from "@/lib/use-live-job";
import { nextPollDelay, settledDeliveries } from "@/lib/delivery";
import {
  badgeStatusFor,
  deriveWorkspaceState,
  elapsedMs,
  formatElapsed,
  isStalled,
  startedAtMs,
} from "@/lib/workspace-state";
import { createRlsClient } from "@/lib/supabase";
import { supabaseFailure } from "@/lib/folio";
import "./workspace.css";

interface ProjectRow {
  id: string;
  language?: string;
  title: string;
  status: string;
  share_token: string | null;
  type?: string | null;
  package_tier?: string | null;
}

interface SourceRow {
  id: string;
  filename: string;
  file_type: string;
  storage_key: string;
  created_at?: string | null;
}

const ACCEPTED =
  ".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv";
// The deck's signed HTML URL lives 15 minutes (DECK_HTML_TTL_SECONDS). Re-mint
// comfortably inside that so a deck left open on screen never rots (G20).
const DECK_REFRESH_MS = 10 * 60 * 1000;
// A read with no deadline is how the audit's eternal skeletons happen: the
// UI cannot tell a slow network from a dead one.
const SUPABASE_TIMEOUT_MS = 15_000;

const TONE_BY_EXT: Record<string, ContextChunk["tone"]> = {
  pdf: "red",
  docx: "accent",
  doc: "accent",
  pptx: "accent",
  csv: "green",
  xlsx: "green",
};

function extensionOf(filename: string | null): string {
  if (!filename) return "";
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot + 1).toLowerCase();
}

function headline(claim: string): string {
  const words = claim.trim().split(/\s+/);
  return words.length <= 6 ? claim.trim() : `${words.slice(0, 6).join(" ")}…`;
}

function toChunk(
  row: ProvenanceRow,
  index: number,
  copy: WorkspaceCopy,
): ContextChunk {
  const ext = extensionOf(row.source_filename);
  // strength was dropped entirely before (G36); it is the whole point of an
  // evidence card, so it leads the meta line.
  const strength = row.strength ? row.strength.toUpperCase() : "";
  const chunk =
    row.chunk_index === null ? "" : `${copy.chunk} ${row.chunk_index}`;
  return {
    key: `claim-${index}`,
    index: index + 1,
    title: headline(row.claim_text),
    meta: [strength, chunk].filter(Boolean).join(" · "),
    body: row.quote ? `${row.claim_text}\n«${row.quote}»` : row.claim_text,
    source: row.source_filename ?? copy.sourceUnknown,
    badge: ext ? ext.toUpperCase() : "MNB",
    tone: TONE_BY_EXT[ext] ?? "orange",
  };
}

type Pane = "chat" | "deck";

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { session, withAuth } = useAppSession();
  const { locale } = useLocale();
  const t = WORKSPACE_COPY[locale];

  const [project, setProject] = useState<ProjectRow | null>(null);
  const [projectError, setProjectError] = useState<unknown>(null);
  const [sources, setSources] = useState<SourceRow[] | null>(null);
  const [sourcesError, setSourcesError] = useState<unknown>(null);
  const [deck, setDeck] = useState<DeckAccessView | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceView | null>(null);
  const [decisions, setDecisions] = useState<DecisionsView | null>(null);
  const [pricing, setPricing] = useState<PricingView | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);

  const [chat, setChat] = useState<ChatHistoryView | null>(null);
  const [draft, setDraft] = useState("");
  const [turnBusy, setTurnBusy] = useState(false);
  const [approving, setApproving] = useState(false);
  const [chatError, setChatError] = useState<unknown>(null);
  const [optimistic, setOptimistic] = useState<ChatThreadMessage[]>([]);

  const [toast, setToast] = useState<{
    message: string;
    danger?: boolean;
  } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [clearSignal, setClearSignal] = useState(0);
  const [enqueueing, setEnqueueing] = useState(false);
  const [enqueueError, setEnqueueError] = useState<unknown>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  // Defaulting to the deck pane hides the run panel behind a tab, so on a
  // phone a queued/processing/failed project opened from the folio showed an
  // empty deck placeholder and nothing about its actual state. The artifact
  // leads only once there IS one; until then the work does.
  const [pane, setPane] = useState<Pane | null>(null);
  // Not read: this exists only to re-render once a second so the elapsed
  // clock and the stall check re-evaluate against a fresh Date.now().
  const [, setTick] = useState(0);

  const fileInput = useRef<HTMLInputElement | null>(null);
  const toastTimer = useRef<number | null>(null);

  const notify = useCallback((message: string, danger?: boolean) => {
    setToast({ message, danger });
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4500);
  }, []);

  // ------------------------------------------------------------ deck + trail

  const loadDeck = useCallback(async () => {
    const view = await withAuth((token) =>
      getDeckAccess(projectId, token),
    ).catch((deckError: unknown) => {
      // 404 is "not ready yet", a wait rather than a failure (G7). The live
      // subscription keeps listening for the decks row.
      if (deckError instanceof ApiError && deckError.status === 404)
        return null;
      throw deckError;
    });
    setDeck(view ?? null);
  }, [projectId, withAuth]);

  const loadProvenance = useCallback(async () => {
    try {
      const view = await withAuth((token) => getProvenance(projectId, token));
      setProvenance(view);
    } catch {
      // Best-effort: the deck stays usable without the evidence trail.
    }
  }, [projectId, withAuth]);

  const loadDecisions = useCallback(async () => {
    try {
      setDecisions(await withAuth((token) => getDecisions(projectId, token)));
    } catch {
      // 404 until a deck exists. Best-effort like provenance: a missing
      // record of decisions must never cost the user the deck itself.
    }
  }, [projectId, withAuth]);

  const onDeckChanged = useCallback(() => {
    void loadDeck();
    void loadProvenance();
    void loadDecisions();
    void withAuth((token) => getChat(projectId, token))
      .then((view) => view && setChat(view))
      .catch(() => undefined);
  }, [loadDeck, loadProvenance, loadDecisions, projectId, withAuth]);

  // Only a deck project has generation jobs, a deck, decisions and a chat; an
  // article project asked for them and collected a 404 for each (and a 404
  // per job poll). Nothing deck-shaped is requested until the type is known.
  const deckProject = project !== null && project.type !== "article";

  const {
    job,
    state: jobState,
    error: jobError,
    live,
    refresh,
  } = useLiveJob({
    projectId,
    session,
    withAuth,
    onDeckChanged,
    enabled: deckProject,
    hasDeck: deck !== null,
  });

  // --------------------------------------------------------------- RLS reads

  const loadProject = useCallback(() => {
    if (!session) return;
    setProjectError(null);
    const supabase = createRlsClient(session.accessToken);
    supabase
      .from("projects")
      .select("*")
      .eq("id", projectId)
      .abortSignal(AbortSignal.timeout(SUPABASE_TIMEOUT_MS))
      // maybeSingle, not single: a row RLS hides (another user's project) is
      // zero rows, which .single() turns into HTTP 406 (PGRST116) and a console
      // error. Zero rows is simply "not found".
      .maybeSingle()
      .then(({ data, error, status }) => {
        // A PostgREST sentence is not user copy (§4 ledger row 6) — but neither
        // is a hardcoded 404. supabase-js RESOLVES on a dead network with
        // status 0, so collapsing every failure onto "project_not_found" told a
        // user with a dropped connection that their project did not exist.
        if (error) setProjectError(supabaseFailure(error, status));
        else if (data === null)
          setProjectError(new ApiError(404, "project_not_found"));
        else {
          const row = data as ProjectRow;
          setProject(row);
          setShareToken(row.share_token);
        }
      }, setProjectError);
  }, [projectId, session]);

  const refreshSources = useCallback(() => {
    if (!session) return;
    setSourcesError(null);
    const supabase = createRlsClient(session.accessToken);
    supabase
      .from("sources")
      .select("id,filename,file_type,storage_key,created_at")
      .eq("project_id", projectId)
      .order("created_at", { ascending: true })
      .abortSignal(AbortSignal.timeout(SUPABASE_TIMEOUT_MS))
      .then(({ data, error, status }) => {
        // The old code toasted the raw PostgREST message for 4s and left the
        // list a permanent skeleton with the CTA disabled and no reason (G33).
        if (error) setSourcesError(supabaseFailure(error, status));
        else setSources((data ?? []) as SourceRow[]);
      }, setSourcesError);
  }, [projectId, session]);

  useEffect(() => {
    if (!session) return;
    loadProject();
    refreshSources();
    getPricing()
      .then(setPricing)
      .catch(() => undefined);
    return () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    };
  }, [session, projectId, loadProject, refreshSources]);

  // Provenance belongs to a project the caller can see: a project RLS hides
  // (another user's) is not asked about at all.
  useEffect(() => {
    if (!session || project === null) return;
    void loadProvenance();
  }, [session, project, loadProvenance]);

  // The deck-shaped reads wait for the project type (see deckProject).
  useEffect(() => {
    if (!session || !deckProject) return;
    void loadDeck();
    void loadDecisions();
    void withAuth((token) => getChat(projectId, token))
      .then((view) => view && setChat(view))
      .catch(() => undefined);
  }, [session, deckProject, projectId, loadDeck, loadDecisions, withAuth]);

  // B1-FIX2: a queued AI edit is applied by a worker, then committed while its
  // render publishes the files. The chat owns that watch: while an edit is
  // applying or delivering, re-read the chat (3 s backing off to 30 s, with or
  // without Realtime). Each read settles finished deliveries server-side, so
  // the "ready" or "saved but not rendered" notice and the restored allowance
  // appear without a reload; a settled delivery also refreshes the downloads.
  const deliveringKey = (chat?.delivering_job_ids ?? []).join(",");
  const applyingId = chat?.applying_job_id ?? null;
  useEffect(() => {
    if (!session || !deckProject) return;
    if (!applyingId && deliveringKey === "") return;
    let delay: number | null = null;
    let stopped = false;
    let timer: number | null = null;
    const previous = deliveringKey === "" ? [] : deliveringKey.split(",");
    const tick = async () => {
      try {
        const view = await withAuth((token) => getChat(projectId, token));
        if (stopped || !view) return;
        const next = view.delivering_job_ids ?? [];
        const settled = settledDeliveries(previous, next);
        if (settled.length > 0 || (applyingId && !view.applying_job_id)) {
          onDeckChanged();
        }
        setChat(view);
      } catch {
        // A blip must not end the watch; the next tick tries again.
      }
      if (stopped) return;
      delay = nextPollDelay(delay);
      timer = window.setTimeout(() => void tick(), delay);
    };
    delay = nextPollDelay(null);
    timer = window.setTimeout(() => void tick(), delay);
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [session, deckProject, applyingId, deliveringKey, projectId, withAuth, onDeckChanged]);

  // Re-mint the signed deck URL before it expires (G20).
  useEffect(() => {
    if (!deck) return;
    const timer = window.setInterval(() => void loadDeck(), DECK_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [deck, loadDeck]);

  // Drives the elapsed clock and the stall check without re-fetching anything.
  useEffect(() => {
    if (job?.status !== "queued" && job?.status !== "processing") return;
    const timer = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [job?.status]);

  // ------------------------------------------------------------------ state

  const workspace = useMemo(
    () =>
      deriveWorkspaceState(project, job, deck !== null, jobState !== "loading"),
    [project, job, deck, jobState],
  );

  const tier = useMemo(() => {
    // The job's own package is authoritative; projects.package_tier is
    // best-effort and can disagree with what was actually charged (G22).
    const fromJob = job?.package ?? null;
    return tierOf(fromJob ?? project?.package_tier);
  }, [job?.package, project?.package_tier]);

  const priced = useMemo(() => {
    const entry = pricing?.packages.find(
      (p) => p.package === (job?.package ?? tier.id),
    );
    return {
      price: job?.deducted_amount ?? entry?.price ?? tier.price,
      images: entry?.ai_images ?? null,
      fixes: entry?.fix_allowance ?? null,
    };
  }, [pricing, job?.package, job?.deducted_amount, tier]);

  const activePane: Pane = pane ?? (deck !== null ? "deck" : "chat");

  const progress = job?.progress ?? {};
  const steps = stepStates(progress, job?.status ?? "queued", locale);
  const activeIndex = steps.findIndex(
    (s) => s.state === "running" || s.state === "failed",
  );
  const taskRows: TaskRow[] = steps.map((entry, index) => ({
    key: entry.key,
    index: index + 1,
    label: entry.label,
    meta: entry.meta,
    status: entry.state,
  }));
  const now = Date.now();
  const stalled = isStalled(job, now);
  const elapsed = elapsedMs(job, now);

  // ----------------------------------------------------------------- actions

  async function onUpload() {
    const file = fileInput.current?.files?.[0];
    if (!file) {
      notify(t.chooseFirst, true);
      return;
    }
    setUploading(true);
    try {
      const presign = await withAuth((token) =>
        presignUpload(projectId, file.name, file.size, token),
      );
      if (!presign) return;
      await uploadToR2(presign, file);
      await withAuth((token) =>
        registerSource(projectId, presign.storage_key, file.name, token),
      );
      if (fileInput.current) fileInput.current.value = "";
      setClearSignal((v) => v + 1);
      notify(t.uploaded(file.name));
      refreshSources();
    } catch (uploadError) {
      notify(describeError(uploadError, locale).message, true);
    } finally {
      setUploading(false);
    }
  }

  async function onEnqueue() {
    if (!sources || sources.length === 0) return;
    setEnqueueing(true);
    setEnqueueError(null);
    try {
      const view = await withAuth((token) =>
        enqueueJob(
          projectId,
          sources.map((s) => ({
            storage_key: s.storage_key,
            filename: s.filename,
          })),
          token,
          undefined,
          project?.language ?? "uz",
        ),
      );
      if (!view) return;
      // Typed since P2 and never read until now (G23): the server deduped, so
      // the deduction was refunded and this is the RUNNING job, not a new one.
      if (view.existing) {
        notify(t.duplicateRun);
      }
      refresh();
    } catch (error) {
      setEnqueueError(error);
    } finally {
      setEnqueueing(false);
    }
  }

  async function onSend() {
    const message = draft.trim();
    if (!message || turnBusy) return;
    setDraft("");
    setChatError(null);
    setTurnBusy(true);
    // Echo the user's own words immediately; the server thread replaces this
    // on the next read.
    setOptimistic([
      { key: `local-${Date.now()}`, role: "user", text: message },
    ]);
    try {
      const turn = await withAuth((token) =>
        postChat(projectId, message, token),
      );
      if (!turn) return;
      const view = await withAuth((token) => getChat(projectId, token));
      if (view) setChat(view);
      setOptimistic([]);
      if (turn.kind === "fix_ready") {
        notify(t.fixStarting);
        refresh();
      }
    } catch (error) {
      setOptimistic([]);
      setDraft(message); // never silently swallow what the user typed
      setChatError(error);
    } finally {
      setTurnBusy(false);
    }
  }

  async function onDecision(approve: boolean) {
    const pending = chat?.pending_action ?? null;
    const decision = pending ? decisionOf(pending) : null;
    if (!decision) return;
    setApproving(true);
    setChatError(null);
    try {
      const turn = await withAuth((token) =>
        approve
          ? approvePending(projectId, decision, token)
          : rejectPending(projectId, decision, token),
      );
      if (!turn) return;
      const view = await withAuth((token) => getChat(projectId, token));
      if (view) setChat(view);
      if (approve) refresh();
    } catch (error) {
      setChatError(error);
      if (reasonOf(error) === "decision_changed") {
        // The decision changed elsewhere: show the one that is parked now.
        const view = await withAuth((token) => getChat(projectId, token)).catch(() => null);
        if (view) setChat(view);
      }
    } finally {
      setApproving(false);
    }
  }

  async function onShare(action: "enable" | "rotate" | "disable") {
    try {
      const view = await withAuth((token) =>
        manageShare(projectId, action, token),
      );
      if (!view) return;
      setShareToken(view.share_token);
      notify(
        action === "disable"
          ? t.shareDisabled
          : action === "rotate"
            ? t.shareRotated
            : t.shareEnabled,
      );
    } catch (error) {
      notify(describeError(error, locale).message, true);
    }
  }

  async function copyShareUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      notify(t.shareCopied);
    } catch {
      notify(t.shareCopyFailed, true);
    }
  }

  const shareUrl =
    shareToken && typeof window !== "undefined"
      ? `${window.location.origin}/p/${shareToken}`
      : null;

  // ---------------------------------------------------------------- render

  if (projectError) {
    const friendly = describeError(projectError, locale);
    return (
      <AppChrome active="projects">
        <ErrorState
          title={friendly.title}
          message={friendly.message}
          onRetry={friendly.action?.kind === "back" ? undefined : loadProject}
        />
        {friendly.action?.kind === "back" && (
          <p className="ws-fine ws-center">
            <Link href="/projects">{t.backProjects}</Link>
          </p>
        )}
      </AppChrome>
    );
  }

  if (project?.type === "article") {
    const sourcePanel = (
      <section className="article-source-card" aria-label={t.sourceLabel}>
        <header>
          <strong>{t.sourceTitle}</strong>
          <span>{sources?.length ?? 0}</span>
        </header>
        {sourcesError !== null && (
          <InlineError error={sourcesError} onRetry={refreshSources} />
        )}
        {sources === null && !sourcesError && (
          <div className="skeleton ws-row-skeleton" />
        )}
        {sources !== null && sources.length === 0 && <p>{t.sourceEmpty}</p>}
        {sources !== null && sources.length > 0 && (
          <ul>
            {sources.map((source) => (
              <li key={source.id}>
                <span>{source.file_type.toUpperCase()}</span>
                <strong>{source.filename}</strong>
              </li>
            ))}
          </ul>
        )}
        <FileField
          inputRef={fileInput}
          id="article-source-file"
          name="article-source-file"
          accept={ACCEPTED}
          disabled={uploading}
          clearSignal={clearSignal}
          label={t.sourceChoose}
          hint={t.sourceHint}
        />
        <Button
          variant="ghost"
          onClick={() => void onUpload()}
          loading={uploading}
        >
          {uploading ? t.sourceUploading : t.sourceUpload}
        </Button>
      </section>
    );
    return (
      <AppChrome active="projects">
        <ArticleWorkspace
          projectId={projectId}
          title={project.title}
          sourcePanel={sourcePanel}
          sourceCount={sources?.length ?? 0}
        />
        {toast && <Toast message={toast.message} danger={toast.danger} />}
      </AppChrome>
    );
  }

  const messages: ChatThreadMessage[] = [
    ...(chat?.messages ?? []).map((m, index) => ({
      key: `m-${index}`,
      role: m.role,
      text: m.text,
    })),
    ...optimistic,
  ];

  const chatDisabledReason = (() => {
    if (workspace.kind === "ready" || chat?.can_edit) return null;
    if (workspace.kind === "processing" || workspace.kind === "queued") {
      return t.chatDisabledRunning;
    }
    return t.chatDisabledEmpty;
  })();

  const fixesLeft = chat ? chat.fixes_remaining : (priced.fixes ?? null);

  const chatFooter = (
    <>
      {chatError !== null && (
        <InlineError error={chatError} onRetry={() => setChatError(null)} />
      )}
      {chat?.applying_job_id && <p className="ws-fine">{t.fixApplying}</p>}
      {!chat?.applying_job_id && (chat?.delivering_job_ids?.length ?? 0) > 0 && (
        <p className="ws-fine">{t.fixDelivering}</p>
      )}
      {!chatDisabledReason && fixesLeft !== null && (
        <p className="ws-fine">
          {t.fixesRemaining}: <DataText>{fixesLeft}</DataText>
          {chat && ` / ${chat.fix_limit}`}
        </p>
      )}
    </>
  );

  const runPanel = (
    <>
      {jobError !== null && (
        <InlineError
          error={jobError}
          onRetry={refresh}
          note={live ? undefined : t.reconnecting}
        />
      )}

      {workspace.kind === "archived" && (
        <EmptyState title={t.archivedTitle} hint={t.archivedHint} />
      )}

      {workspace.kind === "no_job" && (
        <div className="ws-start">
          <p className="ws-lede">{t.startLead}</p>
          <Button
            size="lg"
            onClick={() => void onEnqueue()}
            loading={enqueueing}
            disabled={!sources || sources.length === 0}
          >
            {t.createPresentation}
          </Button>
          <p className="ws-fine">
            {t.charge(t.packageNames[tier.id], soum(priced.price))}
          </p>
          {sources !== null && sources.length === 0 && (
            <p className="ws-fine">{t.needsSource}</p>
          )}
        </div>
      )}

      {workspace.kind === "queued" && (
        <div className="ws-wait">
          <LoadingState label={t.queued} startedAt={startedAtMs(job)} />
          <p className="ws-fine">{t.queuedHint}</p>
        </div>
      )}

      {workspace.kind === "processing" && (
        <div className="ws-live">
          <StreamingText
            text={steps[activeIndex]?.label ?? t.working}
            active
            fill
          />
          <p className="ws-fine">
            {elapsed !== null && (
              <>
                {t.elapsed}: <DataText>{formatElapsed(elapsed)}</DataText>
              </>
            )}
            {live ? ` · ${t.live}` : ` · ${t.refreshing}`}
          </p>
          {stalled && (
            <div className="ws-stall" role="status">
              {t.stalled}
            </div>
          )}
        </div>
      )}

      {(workspace.kind === "processing" || workspace.kind === "failed") && (
        <div className="ws-steps">
          <TaskRows rows={taskRows} />
        </div>
      )}

      {workspace.kind === "failed" && job && (
        <div className="ws-failed">
          <p className="ws-failed-note">
            {describeJobFailure(job.error_message, locale).message}
          </p>
          {/* The refund is a FACT off the job-stamped ledger row, not a guess.
              When it is false we say nothing rather than asserting a negative:
              jobs that failed before the stamp existed carry no evidence. */}
          {job.refunded && (
            <p className="ws-fine">
              {t.refunded}
              {job.deducted_amount ? (
                <>
                  : <DataText>{soum(job.deducted_amount)}</DataText>
                </>
              ) : null}
              .
            </p>
          )}
          {job.error_message && (
            <details className="ws-detail">
              <summary>{t.technical}</summary>
              <code>{job.error_message}</code>
            </details>
          )}
          <Button
            variant="ghost"
            onClick={() => void onEnqueue()}
            loading={enqueueing}
          >
            {t.restart} — <DataText>{soum(priced.price)}</DataText>
          </Button>
          <p className="ws-fine">{t.restartHint}</p>
        </div>
      )}

      {workspace.kind === "delivering" && job && (
        <div className="ws-wait" data-testid="ws-delivering">
          <LoadingState label={t.delivering} startedAt={startedAtMs(job)} />
          <p className="ws-fine">
            {t.deliveringHint}
            {live ? ` · ${t.live}` : ` · ${t.refreshing}`}
          </p>
        </div>
      )}

      {workspace.kind === "delivery_failed" && job && (
        <div className="ws-failed" data-testid="ws-delivery-failed">
          <p className="ws-failed-note">{t.deliveryFailed}</p>
          <p className="ws-fine">{t.deliveryFailedHint}</p>
          {/* The refund is a FACT off the job-stamped ledger row. */}
          {job.refunded && (
            <p className="ws-fine">
              {t.refunded}
              {job.deducted_amount ? (
                <>
                  : <DataText>{soum(job.deducted_amount)}</DataText>
                </>
              ) : null}
              .
            </p>
          )}
          {job.error_message && (
            <details className="ws-detail">
              <summary>{t.technical}</summary>
              <code>{job.error_message}</code>
            </details>
          )}
          <Button
            variant="ghost"
            onClick={() => void onEnqueue()}
            loading={enqueueing}
          >
            {t.restart} — <DataText>{soum(priced.price)}</DataText>
          </Button>
          <p className="ws-fine">{t.restartHint}</p>
        </div>
      )}

      {workspace.kind === "completed_no_deck" && (
        <div className="ws-wait">
          <LoadingState label={t.preparingFiles} startedAt={startedAtMs(job)} />
          <p className="ws-fine">{t.preparingFilesHint}</p>
        </div>
      )}

      {enqueueError !== null && (
        <InlineError
          error={enqueueError}
          onRetry={() => setEnqueueError(null)}
          money
          rate
        />
      )}

      {job && workspace.kind !== "no_job" && (
        <div className="ws-trace">
          <ThinkingState
            working={workspace.kind === "processing"}
            activeLabel={t.processDetails}
            doneLabel={t.processDetails}
            rows={steps.map((entry) => ({
              primary: entry.label,
              secondary: entry.meta,
            }))}
            visible={
              workspace.kind === "failed"
                ? Math.max(activeIndex, 0)
                : workspace.kind === "processing"
                  ? activeIndex + 1
                  : steps.length
            }
            expanded={traceOpen}
            onToggle={setTraceOpen}
          />
        </div>
      )}
    </>
  );

  const artifactPanel = (
    <>
      {deck ? (
        <PresentationDesigner
          projectId={projectId}
          deck={deck}
          onRendered={onDeckChanged}
        />
      ) : (
        <div className="ws-deck-blank">
          {workspace.kind === "processing" ||
          workspace.kind === "queued" ||
          workspace.kind === "delivering" ? (
            <p>{t.deckAppears}</p>
          ) : (
            <p>{t.noDeck}</p>
          )}
        </div>
      )}
    </>
  );

  return (
    <AppChrome active="projects">
      <div className="ws">
        <header className="ws-head">
          {project === null ? (
            <div className="skeleton ws-head-skeleton" />
          ) : (
            <>
              <div className="ws-head-line">
                <h1 className="ws-title">{project.title}</h1>
                <StatusBadge
                  status={badgeStatusFor(workspace.kind, project.status)}
                />
              </div>
              <p className="ws-meta">
                {t.packageNames[tier.id]} ·{" "}
                <DataText>{soum(priced.price)}</DataText>
                {priced.images !== null && (
                  <>
                    {" "}
                    · {priced.images} {t.aiImages}
                  </>
                )}
                {elapsed !== null && workspace.kind === "ready" && (
                  <>
                    {" "}
                    · <DataText>{formatElapsed(elapsed)}</DataText> {t.readyIn}
                  </>
                )}
              </p>
            </>
          )}
        </header>

        <div className="ws-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activePane === "chat"}
            onClick={() => setPane("chat")}
          >
            {t.chat}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activePane === "deck"}
            onClick={() => setPane("deck")}
          >
            {t.presentation}
          </button>
        </div>

        <div className="ws-split" data-pane={activePane}>
          <section className="ws-rail" aria-label={t.railLabel}>
            <div className="ws-run">{runPanel}</div>
            <ChatThread
              messages={messages}
              value={draft}
              onChange={setDraft}
              onSend={() => void onSend()}
              busy={turnBusy}
              disabledReason={chatDisabledReason}
              pending={chat?.pending_action ?? null}
              onApprove={() => void onDecision(true)}
              onReject={() => void onDecision(false)}
              approving={approving}
              footer={chatFooter}
              copy={{
                placeholder: t.chatPlaceholder,
                emptyTitle: t.chatEmptyTitle,
                emptyHint: t.chatEmptyHint,
                approvalLabel: t.approvalLabel,
                approvalTitle: t.approvalTitle,
                approve: t.approve,
                reject: t.reject,
                messageLabel: t.messageLabel,
                sendLabel: t.sendLabel,
              }}
            />
          </section>

          <section className="ws-stage" aria-label={t.presentation}>
            {artifactPanel}

            <details className="ws-drawer">
              <summary>
                {t.sourceTitle} {sources ? `· ${sources.length}` : ""}
              </summary>
              <div className="ws-drawer-body">
                {sourcesError !== null && (
                  <InlineError error={sourcesError} onRetry={refreshSources} />
                )}
                {sources === null && !sourcesError && (
                  <div className="skeleton ws-row-skeleton" />
                )}
                {sources !== null && sources.length === 0 && (
                  <EmptyState title={t.noSourceTitle} hint={t.noSourceHint} />
                )}
                {sources !== null && sources.length > 0 && (
                  <ul className="ws-sources">
                    {sources.map((source) => (
                      <li key={source.id} className="ws-source">
                        <span className="ws-source-badge">
                          {source.file_type.toUpperCase()}
                        </span>
                        <span className="ws-source-name">
                          {source.filename}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {deck && sources !== null && sources.length > 0 && (
                  // G34: a file added after delivery changes nothing until a
                  // re-run, and saying so is the difference between a quiet
                  // no-op and an honest one.
                  <p className="ws-fine">{t.sourceSnapshot}</p>
                )}
                <div className="ws-upload">
                  <FileField
                    inputRef={fileInput}
                    id="source-file"
                    name="source-file"
                    accept={ACCEPTED}
                    disabled={uploading}
                    clearSignal={clearSignal}
                    label={t.sourceChoose}
                    hint={t.sourceHint}
                  />
                  <Button
                    variant="ghost"
                    onClick={() => void onUpload()}
                    loading={uploading}
                  >
                    {uploading ? t.sourceUploading : t.upload}
                  </Button>
                </div>
              </div>
            </details>

            {deck && (
              <details className="ws-drawer">
                <summary>{t.sharing}</summary>
                <div className="ws-drawer-body">
                  {shareUrl ? (
                    <div className="ws-share">
                      <a
                        className="ws-share-url"
                        href={shareUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {shareUrl}
                      </a>
                      <p className="ws-fine">{t.shareActiveHint}</p>
                      <div className="ws-actions">
                        <Button
                          variant="ghost"
                          onClick={() => void copyShareUrl(shareUrl)}
                        >
                          {t.copy}
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => void onShare("rotate")}
                        >
                          {t.rotateLink}
                        </Button>
                        <Button
                          variant="danger"
                          onClick={() => void onShare("disable")}
                        >
                          {t.disable}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="ws-share">
                      <p className="ws-lede">{t.shareLead}</p>
                      <Button onClick={() => void onShare("enable")}>
                        {t.createShare}
                      </Button>
                    </div>
                  )}
                </div>
              </details>
            )}

            {decisions !== null && (
              <details className="ws-drawer">
                <summary>{t.decisions}</summary>
                <div className="ws-drawer-body">
                  {hasArgument(decisions) ? (
                    <>
                      <p className="ws-decide-thesis">{decisions.thesis}</p>
                      {decisions.audience_takeaway !== null && (
                        <p className="ws-fine">
                          {t.audienceTakeaway}: {decisions.audience_takeaway}
                        </p>
                      )}
                      <ol className="ws-decide-sections">
                        {decisions.sections.map((section, index) => (
                          <li key={`${section.section_name}-${index}`}>
                            <span className="ws-decide-section-name">
                              {section.section_name}
                            </span>
                            <span className="ws-decide-phase">
                              {phaseLabel(section.phase, locale)}
                            </span>
                            <span className="ws-decide-section-thesis">
                              {section.thesis}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </>
                  ) : (
                    <p className="ws-fine">{t.legacyPlan}</p>
                  )}

                  <div className="ws-decide-look">
                    <div className="ws-swatches" aria-label={t.palette}>
                      {swatches(decisions, locale).map((swatch) => (
                        <span
                          key={swatch.name}
                          className="ws-swatch"
                          title={`${swatch.name} ${swatch.hex}`}
                        >
                          <span
                            className="ws-swatch-chip"
                            style={{ background: swatch.hex }}
                            aria-hidden
                          />
                          <span className="ws-swatch-name">{swatch.name}</span>
                        </span>
                      ))}
                    </div>
                    <p className="ws-fine">
                      {moodLabel(decisions.mood, locale)} ·{" "}
                      {backgroundLabel(decisions.background_treatment, locale)}{" "}
                      · {decisions.heading_font} / {decisions.body_font}
                    </p>
                    {decisions.image_cohesion_note !== null && (
                      <p className="ws-fine">{decisions.image_cohesion_note}</p>
                    )}
                  </div>

                  <dl className="ws-decide-facts">
                    {decidedFor(decisions, locale).map((fact) => (
                      <div key={fact.label}>
                        <dt>{fact.label}</dt>
                        <dd>{fact.value}</dd>
                      </div>
                    ))}
                  </dl>
                  <p className="ws-fine">{t.defaultDecisions}</p>

                  <ol className="ws-decide-roster">
                    {decisions.slides.map((slide) => (
                      <li key={slide.slide_id}>
                        <span className="ws-decide-num data-text">
                          {slide.slide_number}
                        </span>
                        <span>{slide.title}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </details>
            )}

            <ResearchPanel projectId={projectId} />
            <details className="ws-drawer">
              <summary>
                {t.evidence} {provenance ? `· ${provenance.total_claims}` : ""}
              </summary>
              <div className="ws-drawer-body">
                {provenance === null && (
                  <div className="skeleton ws-row-skeleton" />
                )}
                {provenance !== null && provenance.rows.length === 0 && (
                  // The core promise must not vanish when it is empty (G36).
                  <EmptyState
                    title={t.noEvidenceTitle}
                    hint={t.noEvidenceHint}
                  />
                )}
                {provenance !== null && provenance.rows.length > 0 && (
                  <>
                    <EvidenceMap rows={provenance.rows} />
                    <ContextCards
                      title={t.evidence}
                      count={provenance.total_claims}
                      chunks={provenance.rows.map((row, index) =>
                        toChunk(row, index, t),
                      )}
                    />
                    {provenance.total_claims > provenance.rows.length && (
                      <p className="ws-fine">
                        {t.evidenceShown(
                          provenance.total_claims,
                          provenance.rows.length,
                        )}
                      </p>
                    )}
                  </>
                )}
              </div>
            </details>
          </section>
        </div>
      </div>

      {toast && <Toast message={toast.message} danger={toast.danger} />}
    </AppChrome>
  );
}

/**
 * An error rendered WHERE it happened, with copy a person can act on.
 *
 * Replaces the 4-second raw-string toast the audit found at 22 sites: a toast
 * that self-erases cannot carry a recovery, and `String(err)` is not copy.
 */
function InlineError({
  error,
  onRetry,
  note,
  money,
  rate,
}: {
  error: unknown;
  onRetry?: () => void;
  note?: string;
  money?: boolean;
  rate?: boolean;
}) {
  const { locale } = useLocale();
  const t = WORKSPACE_COPY[locale];
  const reason = reasonOf(error);
  const friendly =
    money && reason === "insufficient_balance"
      ? creditCopy(error, soum, locale)
      : rate && reason === "rate_limited"
        ? rateLimitCopy(error, locale)
        : describeError(error, locale);

  return (
    <div className="ws-inline-error" data-tone={friendly.tone} role="alert">
      <p className="ws-inline-title">{friendly.title}</p>
      <p className="ws-inline-message">{friendly.message}</p>
      {note && <p className="ws-fine">{note}</p>}
      {friendly.action?.kind === "topup" && (
        <p className="ws-fine">
          {t.topUp}{" "}
          <a href="https://t.me/nashr_ai_bot" target="_blank" rel="noreferrer">
            {t.openBot}
          </a>
        </p>
      )}
      <div className="ws-inline-actions">
        {onRetry && friendly.action?.kind !== "topup" && (
          <Button variant="ghost" onClick={onRetry}>
            {friendly.action?.label ?? t.retry}
          </Button>
        )}
      </div>
      {friendly.detail && (
        <details className="ws-detail">
          <summary>{t.technical}</summary>
          <code>{friendly.detail}</code>
        </details>
      )}
    </div>
  );
}
