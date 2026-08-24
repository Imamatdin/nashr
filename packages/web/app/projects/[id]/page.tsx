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

const ACCEPTED = ".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv";
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

function toChunk(row: ProvenanceRow, index: number): ContextChunk {
  const ext = extensionOf(row.source_filename);
  // strength was dropped entirely before (G36); it is the whole point of an
  // evidence card, so it leads the meta line.
  const strength = row.strength ? row.strength.toUpperCase() : "";
  const chunk = row.chunk_index === null ? "" : `bo‘lak ${row.chunk_index}`;
  return {
    key: `claim-${index}`,
    index: index + 1,
    title: headline(row.claim_text),
    meta: [strength, chunk].filter(Boolean).join(" · "),
    body: row.quote ? `${row.claim_text}\n«${row.quote}»` : row.claim_text,
    source: row.source_filename ?? "Manba noma’lum",
    badge: ext ? ext.toUpperCase() : "MNB",
    tone: TONE_BY_EXT[ext] ?? "orange",
  };
}

type Pane = "chat" | "deck";

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { session, withAuth } = useAppSession();

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

  const [toast, setToast] = useState<{ message: string; danger?: boolean } | null>(null);
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
    const view = await withAuth((token) => getDeckAccess(projectId, token)).catch(
      (deckError: unknown) => {
        // 404 is "not ready yet", a wait rather than a failure (G7). The live
        // subscription keeps listening for the decks row.
        if (deckError instanceof ApiError && deckError.status === 404) return null;
        throw deckError;
      },
    );
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

  const { job, state: jobState, error: jobError, live, refresh } = useLiveJob({
    projectId,
    session,
    withAuth,
    onDeckChanged,
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
      .single()
      .then(({ data, error, status }) => {
        // A PostgREST sentence is not user copy (§4 ledger row 6) — but neither
        // is a hardcoded 404. supabase-js RESOLVES on a dead network with
        // status 0, so collapsing every failure onto "project_not_found" told a
        // user with a dropped connection that their project did not exist.
        if (error) setProjectError(supabaseFailure(error, status));
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
    void loadDeck();
    void loadProvenance();
    void loadDecisions();
    void withAuth((token) => getChat(projectId, token))
      .then((view) => view && setChat(view))
      .catch(() => undefined);
    getPricing()
      .then(setPricing)
      .catch(() => undefined);
    return () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    };
  }, [
    session,
    projectId,
    loadProject,
    refreshSources,
    loadDeck,
    loadProvenance,
    loadDecisions,
    withAuth,
  ]);

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
    () => deriveWorkspaceState(project, job, deck !== null, jobState !== "loading"),
    [project, job, deck, jobState],
  );

  const tier = useMemo(() => {
    // The job's own package is authoritative; projects.package_tier is
    // best-effort and can disagree with what was actually charged (G22).
    const fromJob = job?.package ?? null;
    return tierOf(fromJob ?? project?.package_tier);
  }, [job?.package, project?.package_tier]);

  const priced = useMemo(() => {
    const entry = pricing?.packages.find((p) => p.package === (job?.package ?? tier.id));
    return {
      price: job?.deducted_amount ?? entry?.price ?? tier.price,
      images: entry?.ai_images ?? null,
      fixes: entry?.fix_allowance ?? null,
    };
  }, [pricing, job?.package, job?.deducted_amount, tier]);

  const activePane: Pane = pane ?? (deck !== null ? "deck" : "chat");

  const progress = job?.progress ?? {};
  const steps = stepStates(progress, job?.status ?? "queued");
  const activeIndex = steps.findIndex((s) => s.state === "running" || s.state === "failed");
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
      notify("Avval fayl tanlang", true);
      return;
    }
    setUploading(true);
    try {
      const presign = await withAuth((token) =>
        presignUpload(projectId, file.name, file.size, token),
      );
      if (!presign) return;
      await uploadToR2(presign, file);
      await withAuth((token) => registerSource(projectId, presign.storage_key, file.name, token));
      if (fileInput.current) fileInput.current.value = "";
      setClearSignal((v) => v + 1);
      notify(`${file.name} yuklandi`);
      refreshSources();
    } catch (uploadError) {
      notify(describeError(uploadError).message, true);
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
          sources.map((s) => ({ storage_key: s.storage_key, filename: s.filename })),
          token,
        ),
      );
      if (!view) return;
      // Typed since P2 and never read until now (G23): the server deduped, so
      // the deduction was refunded and this is the RUNNING job, not a new one.
      if (view.existing) {
        notify("Bu loyiha allaqachon yaratilmoqda — hisobdan qayta yechilmadi.");
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
    setOptimistic([{ key: `local-${Date.now()}`, role: "user", text: message }]);
    try {
      const turn = await withAuth((token) => postChat(projectId, message, token));
      if (!turn) return;
      const view = await withAuth((token) => getChat(projectId, token));
      if (view) setChat(view);
      setOptimistic([]);
      if (turn.kind === "fix_ready") {
        notify("Tahrir qo‘llanmoqda — taqdimot qayta yig‘ilmoqda.");
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
    setApproving(true);
    setChatError(null);
    try {
      const turn = await withAuth((token) =>
        approve ? approvePending(projectId, token) : rejectPending(projectId, token),
      );
      if (!turn) return;
      const view = await withAuth((token) => getChat(projectId, token));
      if (view) setChat(view);
      if (approve) refresh();
    } catch (error) {
      setChatError(error);
    } finally {
      setApproving(false);
    }
  }

  async function onShare(action: "enable" | "rotate" | "disable") {
    try {
      const view = await withAuth((token) => manageShare(projectId, action, token));
      if (!view) return;
      setShareToken(view.share_token);
      notify(
        action === "disable"
          ? "Havola o‘chirildi"
          : action === "rotate"
            ? "Yangi havola yaratildi. Eskisi bekor bo‘ldi."
            : "Ommaviy havola yoqildi",
      );
    } catch (error) {
      notify(describeError(error).message, true);
    }
  }

  async function copyShareUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      notify("Havola nusxalandi");
    } catch {
      notify("Nusxalab bo‘lmadi. Havolani qo‘lda belgilang.", true);
    }
  }

  const shareUrl =
    shareToken && typeof window !== "undefined"
      ? `${window.location.origin}/p/${shareToken}`
      : null;

  // ---------------------------------------------------------------- render

  if (projectError) {
    const friendly = describeError(projectError);
    return (
      <AppChrome active="projects">
        <ErrorState
          title={friendly.title}
          message={friendly.message}
          onRetry={friendly.action?.kind === "back" ? undefined : loadProject}
        />
        {friendly.action?.kind === "back" && (
          <p className="ws-fine ws-center">
            <Link href="/projects">Loyihalarga qaytish</Link>
          </p>
        )}
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
      return "Taqdimot tayyor bo‘lgach, shu yerda uni tahrirlaysiz.";
    }
    return "Suhbat taqdimot tayyor bo‘lgandan keyin ochiladi — u tayyor slaydlar ustida ishlaydi.";
  })();

  const fixesLeft = chat ? chat.fixes_remaining : (priced.fixes ?? null);

  const chatFooter = (
    <>
      {chatError !== null && <InlineError error={chatError} onRetry={() => setChatError(null)} />}
      {chat?.applying_job_id && (
        <p className="ws-fine">Tahrir qo‘llanmoqda — bir necha daqiqa.</p>
      )}
      {!chatDisabledReason && fixesLeft !== null && (
        <p className="ws-fine">
          Qolgan tahrirlar: <DataText>{fixesLeft}</DataText>
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
          note={live ? undefined : "Holat yangilanmayapti — qayta ulanmoqda."}
        />
      )}

      {workspace.kind === "article_project" && (
        <EmptyState
          title="Maqola — tez kunda"
          hint="Bu loyiha maqola sifatida boshlangan. Maqola muharriri hali web’da ochilmagan; hozircha uni Telegram botda davom ettirasiz."
        />
      )}

      {workspace.kind === "archived" && (
        <EmptyState
          title="Arxivlangan loyiha"
          hint="Bu loyiha arxivda. Uni ko‘rish mumkin, lekin yangi generatsiya boshlanmaydi."
        />
      )}

      {workspace.kind === "no_job" && (
        <div className="ws-start">
          <p className="ws-lede">
            Manbalar tayyor bo‘lgach, taqdimotni buyurtma qiling. Odatda 3-6 daqiqa davom
            etadi.
          </p>
          <Button
            size="lg"
            onClick={() => void onEnqueue()}
            loading={enqueueing}
            disabled={!sources || sources.length === 0}
          >
            Taqdimot yaratish
          </Button>
          <p className="ws-fine">
            Hisobdan {tier.name} paketi yechiladi: <DataText>{soum(priced.price)}</DataText>.
            Muvaffaqiyatsiz bo‘lsa avtomatik qaytariladi.
          </p>
          {sources !== null && sources.length === 0 && (
            <p className="ws-fine">Kamida bitta manba kerak — quyida yuklang.</p>
          )}
        </div>
      )}

      {workspace.kind === "queued" && (
        <div className="ws-wait">
          <LoadingState label="Navbatda" startedAt={startedAtMs(job)} />
          <p className="ws-fine">Ish navbatga qo‘yildi. Birinchi bosqich boshlanmoqda.</p>
        </div>
      )}

      {workspace.kind === "processing" && (
        <div className="ws-live">
          <StreamingText text={steps[activeIndex]?.label ?? "Ishlanmoqda"} active fill />
          <p className="ws-fine">
            {elapsed !== null && <>Ketgan vaqt: <DataText>{formatElapsed(elapsed)}</DataText></>}
            {live ? " · jonli" : " · yangilanmoqda"}
          </p>
          {stalled && (
            <div className="ws-stall" role="status">
              Ish 45 soniyadan beri javob bermayapti. Odatda o‘zi tiklanadi — tiklanmasa,
              kredit avtomatik qaytariladi.
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
          <p className="ws-failed-note">{describeJobFailure(job.error_message).message}</p>
          {/* The refund is a FACT off the job-stamped ledger row, not a guess.
              When it is false we say nothing rather than asserting a negative:
              jobs that failed before the stamp existed carry no evidence. */}
          {job.refunded && (
            <p className="ws-fine">
              Kredit qaytarildi
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
              <summary>Texnik tafsilot</summary>
              <code>{job.error_message}</code>
            </details>
          )}
          <Button variant="ghost" onClick={() => void onEnqueue()} loading={enqueueing}>
            Qaytadan boshlash — <DataText>{soum(priced.price)}</DataText>
          </Button>
          <p className="ws-fine">
            Bu yangi generatsiya: jarayon birinchi bosqichdan boshlanadi va hisobdan qayta
            yechiladi.
          </p>
        </div>
      )}

      {workspace.kind === "completed_no_deck" && (
        <div className="ws-wait">
          <LoadingState label="Fayllar tayyorlanmoqda" startedAt={startedAtMs(job)} />
          <p className="ws-fine">Taqdimot yig‘ildi — fayllar hozir joylanmoqda.</p>
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
            activeLabel="Jarayon tafsiloti"
            doneLabel="Jarayon tafsiloti"
            rows={steps.map((entry) => ({ primary: entry.label, secondary: entry.meta }))}
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
        <>
          <div className="ws-deck-bar">
            <div className="ws-actions">
              {deck.downloads.map((download) => (
                <a
                  key={download.format}
                  href={download.url}
                  download
                  className="btn btn-ghost ws-download"
                >
                  <span className="btn-label">{download.format.toUpperCase()}</span>
                </a>
              ))}
              <a
                href={deck.html_url}
                target="_blank"
                rel="noreferrer"
                className="btn btn-ghost ws-download"
              >
                <span className="btn-label">To‘liq ekran</span>
              </a>
            </div>
          </div>
          <div className="ws-deck">
            <iframe
              src={deck.html_url}
              sandbox="allow-scripts"
              title="Taqdimot"
              // Opportunistic only: an iframe does not fire onError for an
              // HTTP error inside it (R2 serves its own body and the frame
              // counts as loaded). The DECK_REFRESH_MS interval above is what
              // actually keeps the signed URL from rotting (G20).
              onError={() => void loadDeck()}
            />
          </div>
        </>
      ) : (
        <div className="ws-deck-blank">
          {workspace.kind === "processing" || workspace.kind === "queued" ? (
            <p>Taqdimot shu yerda paydo bo‘ladi.</p>
          ) : (
            <p>Hali taqdimot yo‘q.</p>
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
                <StatusBadge status={badgeStatusFor(workspace.kind, project.status)} />
              </div>
              <p className="ws-meta">
                {tier.name} · <DataText>{soum(priced.price)}</DataText>
                {priced.images !== null && <> · {priced.images} AI rasm</>}
                {elapsed !== null && workspace.kind === "ready" && (
                  <> · <DataText>{formatElapsed(elapsed)}</DataText> ichida tayyorlandi</>
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
            Suhbat
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activePane === "deck"}
            onClick={() => setPane("deck")}
          >
            Taqdimot
          </button>
        </div>

        <div className="ws-split" data-pane={activePane}>
          <section className="ws-rail" aria-label="Suhbat va jarayon">
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
            />
          </section>

          <section className="ws-stage" aria-label="Taqdimot">
            {artifactPanel}

            <details className="ws-drawer">
              <summary>Manbalar {sources ? `· ${sources.length}` : ""}</summary>
              <div className="ws-drawer-body">
                {sourcesError !== null && (
                  <InlineError error={sourcesError} onRetry={refreshSources} />
                )}
                {sources === null && !sourcesError && <div className="skeleton ws-row-skeleton" />}
                {sources !== null && sources.length === 0 && (
                  <EmptyState
                    title="Manba yuklanmagan"
                    hint="Taqdimot faqat siz yuklagan fayllardagi faktlarga tayanadi. PDF, DOCX yoki PPTX yuklang (maks. 20 MB)."
                  />
                )}
                {sources !== null && sources.length > 0 && (
                  <ul className="ws-sources">
                    {sources.map((source) => (
                      <li key={source.id} className="ws-source">
                        <span className="ws-source-badge">{source.file_type.toUpperCase()}</span>
                        <span className="ws-source-name">{source.filename}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {deck && sources !== null && sources.length > 0 && (
                  // G34: a file added after delivery changes nothing until a
                  // re-run, and saying so is the difference between a quiet
                  // no-op and an honest one.
                  <p className="ws-fine">
                    Taqdimot shu manbalar asosida yig‘ilgan. Yangi fayl qo‘shsangiz, uni
                    qo‘shish uchun qaytadan yaratish kerak.
                  </p>
                )}
                <div className="ws-upload">
                  <FileField
                    inputRef={fileInput}
                    id="source-file"
                    name="source-file"
                    accept={ACCEPTED}
                    disabled={uploading}
                    clearSignal={clearSignal}
                    label="Fayl tanlash"
                    hint="PDF, DOCX, PPTX. Maks. 20 MB."
                  />
                  <Button variant="ghost" onClick={() => void onUpload()} loading={uploading}>
                    {uploading ? "Yuklanmoqda" : "Yuklash"}
                  </Button>
                </div>
              </div>
            </details>

            {deck && (
              <details className="ws-drawer">
                <summary>Ulashish</summary>
                <div className="ws-drawer-body">
                  {shareUrl ? (
                    <div className="ws-share">
                      <a className="ws-share-url" href={shareUrl} target="_blank" rel="noreferrer">
                        {shareUrl}
                      </a>
                      <p className="ws-fine">
                        Havola siz o‘chirmaguningizcha ishlaydi. Yangilasangiz, eskisi darhol
                        bekor bo‘ladi.
                      </p>
                      <div className="ws-actions">
                        <Button variant="ghost" onClick={() => void copyShareUrl(shareUrl)}>
                          Nusxalash
                        </Button>
                        <Button variant="ghost" onClick={() => void onShare("rotate")}>
                          Havolani yangilash
                        </Button>
                        <Button variant="danger" onClick={() => void onShare("disable")}>
                          O‘chirish
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="ws-share">
                      <p className="ws-lede">
                        Ommaviy havola taqdimotni istalgan kishiga, kirmasdan, ko‘rsatadi.
                      </p>
                      <Button onClick={() => void onShare("enable")}>
                        Ommaviy havola yaratish
                      </Button>
                    </div>
                  )}
                </div>
              </details>
            )}

            {decisions !== null && (
              <details className="ws-drawer">
                <summary>Nima qaror qilindi</summary>
                <div className="ws-drawer-body">
                  {hasArgument(decisions) ? (
                    <>
                      <p className="ws-decide-thesis">{decisions.thesis}</p>
                      {decisions.audience_takeaway !== null && (
                        <p className="ws-fine">
                          Tinglovchi nima bilan chiqadi: {decisions.audience_takeaway}
                        </p>
                      )}
                      <ol className="ws-decide-sections">
                        {decisions.sections.map((section, index) => (
                          <li key={`${section.section_name}-${index}`}>
                            <span className="ws-decide-section-name">
                              {section.section_name}
                            </span>
                            <span className="ws-decide-phase">{phaseLabel(section.phase)}</span>
                            <span className="ws-decide-section-thesis">{section.thesis}</span>
                          </li>
                        ))}
                      </ol>
                    </>
                  ) : (
                    <p className="ws-fine">
                      Bu taqdimot reja mexanizmi joriy qilinishidan oldin yaratilgan, shuning
                      uchun uning yozma argumenti saqlanmagan. Dizayn va slaydlar ro‘yxati
                      quyida.
                    </p>
                  )}

                  <div className="ws-decide-look">
                    <div className="ws-swatches" aria-label="Rang palitrasi">
                      {swatches(decisions).map((swatch) => (
                        <span key={swatch.name} className="ws-swatch" title={`${swatch.name} ${swatch.hex}`}>
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
                      {moodLabel(decisions.mood)} · {backgroundLabel(decisions.background_treatment)}{" "}
                      · {decisions.heading_font} / {decisions.body_font}
                    </p>
                    {decisions.image_cohesion_note !== null && (
                      <p className="ws-fine">{decisions.image_cohesion_note}</p>
                    )}
                  </div>

                  <dl className="ws-decide-facts">
                    {decidedFor(decisions).map((fact) => (
                      <div key={fact.label}>
                        <dt>{fact.label}</dt>
                        <dd>{fact.value}</dd>
                      </div>
                    ))}
                  </dl>
                  <p className="ws-fine">
                    Savollarga javob bermagan bo‘lsangiz, bu tanlovlarni manbalaringiz
                    asosida Nashr o‘zi qildi.
                  </p>

                  <ol className="ws-decide-roster">
                    {decisions.slides.map((slide) => (
                      <li key={slide.slide_id}>
                        <span className="ws-decide-num data-text">{slide.slide_number}</span>
                        <span>{slide.title}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </details>
            )}

            <details className="ws-drawer">
              <summary>
                Dalillar {provenance ? `· ${provenance.total_claims}` : ""}
              </summary>
              <div className="ws-drawer-body">
                {provenance === null && <div className="skeleton ws-row-skeleton" />}
                {provenance !== null && provenance.rows.length === 0 && (
                  // The core promise must not vanish when it is empty (G36).
                  <EmptyState
                    title="Dalil topilmadi"
                    hint="Bu taqdimot uchun manbalardan da’vo ajratilmagan. Matnli PDF yoki DOCX yuklasangiz, dalillar shu yerda ko‘rinadi."
                  />
                )}
                {provenance !== null && provenance.rows.length > 0 && (
                  <>
                    <ContextCards
                      title="Dalillar"
                      count={provenance.total_claims}
                      chunks={provenance.rows.map(toChunk)}
                    />
                    {provenance.total_claims > provenance.rows.length && (
                      <p className="ws-fine">
                        {provenance.total_claims} ta da’vodan birinchi{" "}
                        <DataText>{provenance.rows.length}</DataText> tasi ko‘rsatilgan.
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
  const reason = reasonOf(error);
  const friendly =
    money && reason === "insufficient_balance"
      ? creditCopy(error, soum)
      : rate && reason === "rate_limited"
        ? rateLimitCopy(error)
        : describeError(error);

  return (
    <div className="ws-inline-error" data-tone={friendly.tone} role="alert">
      <p className="ws-inline-title">{friendly.title}</p>
      <p className="ws-inline-message">{friendly.message}</p>
      {note && <p className="ws-fine">{note}</p>}
      {friendly.action?.kind === "topup" && (
        <p className="ws-fine">
          To‘lov hozircha Telegram botda:{" "}
          <a href="https://t.me/nashr_ai_bot" target="_blank" rel="noreferrer">
            botni ochish
          </a>
        </p>
      )}
      <div className="ws-inline-actions">
        {onRetry && friendly.action?.kind !== "topup" && (
          <Button variant="ghost" onClick={onRetry}>
            {friendly.action?.label ?? "Qayta urinish"}
          </Button>
        )}
      </div>
      {friendly.detail && (
        <details className="ws-detail">
          <summary>Texnik tafsilot</summary>
          <code>{friendly.detail}</code>
        </details>
      )}
    </div>
  );
}
