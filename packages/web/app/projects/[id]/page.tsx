"use client";

// Project workspace: upload sources, enqueue, watch progress by polling, then the
// delivered deck inline with downloads, share controls and the provenance trail.
// Reads ride RLS (project row, sources list); every mutation and signed-URL mint
// goes through the API. The presentation is a single hairline-separated column;
// the pipeline is the ported TaskRows (#06) with ThinkingState (#02) as its
// trace, LoadingState (#01) for the indeterminate wait, StreamingText (#03) for
// the live step line and ContextCards (#10) for provenance.

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppChrome } from "@/components/chrome";
import {
  ContextCards,
  LoadingState,
  StreamingText,
  TaskRows,
  ThinkingState,
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
  type DeckAccessView,
  type JobView,
  type ProvenanceRow,
  type ProvenanceView,
  enqueueJob,
  getDeckAccess,
  getJob,
  getProvenance,
  manageShare,
  presignUpload,
  registerSource,
  uploadToR2,
} from "@/lib/api";
import { type AppSession, loadSession } from "@/lib/session";
import { createRlsClient } from "@/lib/supabase";
import "./workspace.css";

interface ProjectRow {
  id: string;
  title: string;
  status: string;
  share_token: string | null;
  // Migration 010 may be unapplied, so the column is never named in the select
  // and arrives as undefined on older databases.
  package_tier?: string | null;
}

interface SourceRow {
  id: string;
  filename: string;
  file_type: string;
  storage_key: string;
}

const POLL_INTERVAL_MS = 3000;
const ACCEPTED = ".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv";

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

/** The claim's opening words carry the card; the full text sits in the body. */
function headline(claim: string): string {
  const words = claim.trim().split(/\s+/);
  return words.length <= 6 ? claim.trim() : `${words.slice(0, 6).join(" ")}…`;
}

function toChunk(row: ProvenanceRow, index: number): ContextChunk {
  const ext = extensionOf(row.source_filename);
  return {
    key: `claim-${index}`,
    title: headline(row.claim_text),
    meta: row.chunk_index === null ? "" : `bo‘lak ${row.chunk_index}`,
    // ContextChunk.body is a plain string, so the quote rides a second line
    // that workspace.css renders with pre-line and a quieter colour.
    body: row.quote ? `${row.claim_text}\n«${row.quote}»` : row.claim_text,
    source: row.source_filename ?? "Manba noma’lum",
    badge: ext ? ext.toUpperCase() : "MNB",
    tone: TONE_BY_EXT[ext] ?? "orange",
  };
}

export default function ProjectPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const projectId = params.id;

  const [session, setSession] = useState<AppSession | null>(null);
  const [project, setProject] = useState<ProjectRow | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceRow[] | null>(null);
  const [toast, setToast] = useState<{ message: string; danger?: boolean } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [clearSignal, setClearSignal] = useState(0);
  const [job, setJob] = useState<JobView | null>(null);
  const [enqueueing, setEnqueueing] = useState(false);
  const [deck, setDeck] = useState<DeckAccessView | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceView | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const pollTimer = useRef<number | null>(null);
  const toastTimer = useRef<number | null>(null);

  function notify(message: string, danger?: boolean) {
    setToast({ message, danger });
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4000);
  }

  const loadProject = useCallback(
    (activeSession: AppSession) => {
      setProjectError(null);
      const supabase = createRlsClient(activeSession.accessToken);
      supabase
        .from("projects")
        .select("*")
        .eq("id", projectId)
        .single()
        .then(({ data, error: queryError }) => {
          if (queryError) setProjectError(queryError.message);
          else {
            const row = data as ProjectRow;
            setProject(row);
            setShareToken(row.share_token);
          }
        });
    },
    [projectId],
  );

  const refreshSources = useCallback(
    (activeSession: AppSession) => {
      const supabase = createRlsClient(activeSession.accessToken);
      supabase
        .from("sources")
        .select("id,filename,file_type,storage_key")
        .eq("project_id", projectId)
        .order("created_at", { ascending: true })
        .then(({ data, error: queryError }) => {
          if (queryError) notify(queryError.message, true);
          else setSources((data ?? []) as SourceRow[]);
        });
    },
    [projectId],
  );

  const loadDeck = useCallback(
    async (activeSession: AppSession) => {
      try {
        setDeck(await getDeckAccess(projectId, activeSession.accessToken));
      } catch (deckError) {
        if (!(deckError instanceof ApiError && deckError.status === 404)) {
          notify(String(deckError), true);
        }
      }
      try {
        setProvenance(await getProvenance(projectId, activeSession.accessToken));
      } catch {
        // Provenance is best-effort display; the deck stays usable without it.
      }
    },
    [projectId],
  );

  useEffect(() => {
    const active = loadSession();
    if (!active) {
      router.replace(
        "/login?returnTo=" +
          encodeURIComponent(window.location.pathname + window.location.search),
      );
      return;
    }
    setSession(active);
    loadProject(active);
    refreshSources(active);
    void loadDeck(active);
    return () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    };
  }, [projectId, router, loadProject, refreshSources, loadDeck]);

  const pollJob = useCallback(
    (jobId: string, activeSession: AppSession) => {
      getJob(jobId, activeSession.accessToken)
        .then((view) => {
          setJob(view);
          if (view.status === "queued" || view.status === "processing") {
            pollTimer.current = window.setTimeout(
              () => pollJob(jobId, activeSession),
              POLL_INTERVAL_MS,
            );
          } else if (view.status === "completed") {
            notify("Taqdimot tayyor!");
            void loadDeck(activeSession);
          }
        })
        .catch((pollError) => notify(String(pollError), true));
    },
    [loadDeck],
  );

  // /new enqueues, then hands the job over in the URL. useSearchParams would
  // force this page under a Suspense boundary; window.location in the effect
  // reads the same value without it.
  useEffect(() => {
    if (!session) return;
    const jobId = new URLSearchParams(window.location.search).get("job");
    if (jobId) pollJob(jobId, session);
  }, [session, pollJob]);

  async function onUpload() {
    if (!session) return;
    const file = fileInput.current?.files?.[0];
    if (!file) {
      notify("Avval fayl tanlang", true);
      return;
    }
    setUploading(true);
    try {
      const presign = await presignUpload(projectId, file.name, file.size, session.accessToken);
      await uploadToR2(presign, file);
      await registerSource(projectId, presign.storage_key, file.name, session.accessToken);
      if (fileInput.current) fileInput.current.value = "";
      setClearSignal((value) => value + 1);
      notify(`${file.name} yuklandi`);
      refreshSources(session);
    } catch (uploadError) {
      notify(String(uploadError), true);
    } finally {
      setUploading(false);
    }
  }

  async function onEnqueue() {
    if (!session || !sources) return;
    setEnqueueing(true);
    try {
      const view = await enqueueJob(
        projectId,
        sources.map((s) => ({ storage_key: s.storage_key, filename: s.filename })),
        session.accessToken,
      );
      setJob(view);
      pollJob(view.id, session);
    } catch (enqueueError) {
      notify(String(enqueueError), true);
    } finally {
      setEnqueueing(false);
    }
  }

  async function onShare(action: "enable" | "rotate" | "disable") {
    if (!session) return;
    try {
      const view = await manageShare(projectId, action, session.accessToken);
      setShareToken(view.share_token);
      notify(
        action === "disable"
          ? "Havola o‘chirildi"
          : action === "rotate"
            ? "Yangi havola yaratildi. Eskisi bekor bo‘ldi."
            : "Ommaviy havola yoqildi",
      );
    } catch (shareError) {
      notify(String(shareError), true);
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

  const status = job?.status ?? null;
  const queued = status === "queued";
  const processing = status === "processing";
  const running = queued || processing;
  const progress = job?.progress ?? {};
  const steps = stepStates(progress, status ?? "queued");
  const activeIndex = steps.findIndex(
    (entry) => entry.state === "running" || entry.state === "failed",
  );
  const runningLabel = activeIndex >= 0 ? steps[activeIndex].label : "";
  const taskRows: TaskRow[] = steps.map((entry, index) => ({
    key: entry.key,
    index: index + 1,
    label: entry.label,
    meta: `${index + 1}/7`,
    status: entry.state,
  }));
  const traceVisible =
    status === "failed" ? Math.max(activeIndex, 0) : processing ? activeIndex + 1 : steps.length;
  const tier = tierOf(project?.package_tier);
  const shareUrl =
    shareToken && typeof window !== "undefined"
      ? `${window.location.origin}/p/${shareToken}`
      : null;

  if (projectError) {
    return (
      <AppChrome active="projects">
        <ErrorState
          title="Loyiha ochilmadi"
          message={projectError}
          onRetry={session ? () => loadProject(session) : undefined}
        />
      </AppChrome>
    );
  }

  const trace = status !== null && !queued && (
    <div className="ws-trace">
      <ThinkingState
        working={processing}
        activeLabel="Jarayon tafsiloti"
        doneLabel="Jarayon tafsiloti"
        rows={steps.map((entry) => ({ primary: entry.label }))}
        visible={traceVisible}
        expanded={traceOpen}
        onToggle={setTraceOpen}
      />
    </div>
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
                <StatusBadge status={running && status ? status : project.status} />
              </div>
              <p className="ws-meta">
                {tier.name} · <DataText>{soum(tier.price)}</DataText>
              </p>
            </>
          )}
        </header>

        <section className="ws-section">
          <div className="ws-section-head">
            <h2>Manbalar</h2>
            {sources !== null && sources.length > 0 && (
              <DataText className="ws-count">{sources.length} ta</DataText>
            )}
          </div>

          {sources === null && <div className="skeleton ws-row-skeleton" />}

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
        </section>

        <section className="ws-section">
          <div className="ws-section-head">
            <h2>Generatsiya</h2>
            {job && !running && <StatusBadge status={job.status} />}
          </div>

          {!job && (
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
                Hisobdan {tier.name} paketi yechiladi: <DataText>{soum(tier.price)}</DataText>
              </p>
            </div>
          )}

          {queued && (
            <div className="ws-wait">
              <LoadingState label="Navbatda" />
              <p className="ws-fine">Ish navbatga qo‘yildi. Birinchi bosqich boshlanmoqda.</p>
            </div>
          )}

          {processing && (
            <div className="ws-live">
              <StreamingText text={runningLabel} active fill />
            </div>
          )}

          {(processing || status === "failed") && (
            <div className="ws-steps">
              <TaskRows rows={taskRows} onRetry={() => void onEnqueue()} />
            </div>
          )}

          {status === "failed" && (
            <div className="ws-failed">
              <p className="ws-failed-note">
                {job?.error_message ?? "Noma’lum xato. Kredit qaytarildi."}
              </p>
              <Button variant="ghost" onClick={() => void onEnqueue()} loading={enqueueing}>
                Qayta urinish
              </Button>
            </div>
          )}

          {status === "completed" && !deck && (
            <p className="ws-lede">Taqdimot tayyor. Fayllar tayyorlanmoqda.</p>
          )}

          {trace}
        </section>

        {deck && (
          <section className="ws-section">
            <div className="ws-section-head">
              <h2>Taqdimot</h2>
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
              </div>
            </div>
            <div className="ws-deck">
              <iframe src={deck.html_url} sandbox="allow-scripts" title="Taqdimot" />
            </div>
          </section>
        )}

        {deck && (
          <section className="ws-section">
            <div className="ws-section-head">
              <h2>Ulashish</h2>
            </div>
            {shareUrl ? (
              <div className="ws-share">
                <a className="ws-share-url" href={shareUrl} target="_blank" rel="noreferrer">
                  {shareUrl}
                </a>
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
                  Ommaviy havola taqdimotni istalgan kishiga, kirmasdan, ko‘rsatadi. Havolani
                  yangilasangiz eskisi darhol bekor bo‘ladi.
                </p>
                <Button onClick={() => void onShare("enable")}>Ommaviy havola yaratish</Button>
              </div>
            )}
          </section>
        )}

        {provenance && provenance.rows.length > 0 && (
          <section className="ws-section ws-provenance">
            <ContextCards
              title="Dalillar"
              count={provenance.total_claims}
              chunks={provenance.rows.map(toChunk)}
            />
          </section>
        )}
      </div>

      {toast && <Toast message={toast.message} danger={toast.danger} />}
    </AppChrome>
  );
}
