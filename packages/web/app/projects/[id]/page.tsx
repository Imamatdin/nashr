"use client";

// Project workspace (P3 item 2, moved into the P3.6 chrome): upload sources, enqueue,
// watch progress by polling, then the delivered deck inline with downloads,
// share controls and the provenance table. Reads ride RLS (sources list);
// every mutation and signed-URL mint goes through the API.

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppChrome } from "@/components/chrome";
import {
  Button,
  DataText,
  EmptyState,
  ErrorState,
  FileField,
  GenerationSteps,
  Skeleton,
  StatusBadge,
  Toast,
} from "@/components/ui";
import {
  ApiError,
  type DeckAccessView,
  type JobView,
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

interface ProjectRow {
  id: string;
  title: string;
  status: string;
  share_token: string | null;
}

interface SourceRow {
  id: string;
  filename: string;
  file_type: string;
  storage_key: string;
}

const POLL_INTERVAL_MS = 3000;
const ACCEPTED = ".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv";

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
        .select("id,title,status,share_token")
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
          ? "Havola o'chirildi"
          : action === "rotate"
            ? "Yangi havola yaratildi — eskisi bekor bo'ldi"
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
      notify("Nusxalab bo'lmadi — havolani qo'lda belgilang", true);
    }
  }

  const running = job !== null && (job.status === "queued" || job.status === "processing");
  const progress = job?.progress ?? {};
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

  return (
    <AppChrome active="projects">
      {project === null ? (
        <div
          className="skeleton"
          style={{ height: "2.2rem", width: "40%", marginBottom: "var(--sp-5)" }}
        />
      ) : (
        <div className="page-bar">
          <div className="page-head">
            <p className="kicker">Loyiha</p>
            <h1 className="page-title">{project.title}</h1>
          </div>
          <StatusBadge status={running ? "processing" : project.status} />
        </div>
      )}

      <div className="card">
        <div className="card-title">
          <h2>Manbalar</h2>
          {sources !== null && sources.length > 0 && (
            <DataText className="page-count">{sources.length} ta</DataText>
          )}
        </div>
        {sources === null && <Skeleton lines={2} />}
        {sources !== null && sources.length === 0 && (
          <EmptyState
            title="Manba yuklanmagan"
            hint="Taqdimot faqat siz yuklagan fayllardagi faktlarga tayanadi. PDF, DOCX yoki PPTX yuklang (maks. 20 MB)."
          />
        )}
        {sources !== null && sources.length > 0 && (
          <div className="source-list">
            {sources.map((s) => (
              <div key={s.id} className="source-row">
                <span className="file-chip">{s.file_type}</span>
                <span className="source-name">{s.filename}</span>
              </div>
            ))}
          </div>
        )}
        <div className="upload-row">
          <FileField
            inputRef={fileInput}
            id="source-file"
            name="source-file"
            accept={ACCEPTED}
            disabled={uploading}
            clearSignal={clearSignal}
            label="Fayl tanlash"
            hint="PDF, DOCX, PPTX — maks. 20 MB"
          />
          <Button variant="ghost" onClick={() => void onUpload()} loading={uploading}>
            {uploading ? "Yuklanmoqda" : "Yuklash"}
          </Button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h2>Generatsiya</h2>
          {/* While the press runs, the step line states the status better than a
              stamp — and the header already carries one. */}
          {job && !running && <StatusBadge status={job.status} />}
        </div>

        {!job && (
          <>
            <p className="card-lede">
              Manbalar tayyor bo'lgach, taqdimotni buyurtma qiling. Odatda 3–6 daqiqa davom etadi.
            </p>
            <Button
              gilded
              size="lg"
              onClick={() => void onEnqueue()}
              loading={enqueueing}
              disabled={!sources || sources.length === 0}
            >
              Taqdimot yaratish
            </Button>
          </>
        )}

        {running && <GenerationSteps step={progress.step} current={progress.current} />}

        {job?.status === "failed" && (
          <ErrorState
            title="Generatsiya muvaffaqiyatsiz tugadi"
            message={job.error_message ?? "Noma'lum xato. Kredit qaytarildi."}
            onRetry={() => void onEnqueue()}
          />
        )}

        {job?.status === "completed" && (
          <p className="card-lede card-lede-ok">Taqdimot tayyor — quyida ko'ring.</p>
        )}
      </div>

      {deck && (
        <>
          <div className="card">
            <div className="card-title">
              <h2>Taqdimot</h2>
              <div className="btn-row">
                {deck.downloads.map((d) => (
                  <a key={d.format} href={d.url} download className="btn btn-ghost">
                    {d.format.toUpperCase()}
                  </a>
                ))}
              </div>
            </div>
            <iframe
              className="viewer-frame"
              src={deck.html_url}
              sandbox="allow-scripts"
              title="Taqdimot"
            />
          </div>

          <div className="card">
            <div className="card-title">
              <h2>Ulashish</h2>
            </div>
            {shareUrl ? (
              <>
                <p className="share-url">
                  <a href={shareUrl} target="_blank" rel="noreferrer">
                    {shareUrl}
                  </a>
                </p>
                <div className="btn-row">
                  <Button variant="ghost" onClick={() => void copyShareUrl(shareUrl)}>
                    Nusxalash
                  </Button>
                  <Button variant="ghost" onClick={() => void onShare("rotate")}>
                    Havolani yangilash
                  </Button>
                  <Button variant="danger" onClick={() => void onShare("disable")}>
                    O'chirish
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="card-lede">
                  Ommaviy havola taqdimotni istalgan kishiga — kirmasdan — ko'rsatadi. Havolani
                  yangilasangiz, eskisi darhol bekor bo'ladi.
                </p>
                <Button onClick={() => void onShare("enable")}>Ommaviy havola yaratish</Button>
              </>
            )}
          </div>
        </>
      )}

      {provenance && provenance.rows.length > 0 && (
        <div className="card">
          <div className="card-title">
            <h2>Dalillar</h2>
            <DataText className="page-count">{provenance.total_claims} ta da'vo</DataText>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Da'vo</th>
                  <th>Iqtibos</th>
                  <th>Manba</th>
                  <th>Bo'lak</th>
                </tr>
              </thead>
              <tbody>
                {provenance.rows.map((row, index) => (
                  <tr key={index}>
                    <td>{row.claim_text}</td>
                    <td className="table-quiet">{row.quote ?? "—"}</td>
                    <td>{row.source_filename ?? "—"}</td>
                    <td>
                      {row.chunk_index === null ? (
                        "—"
                      ) : (
                        <span className="cite-mark" style={{ verticalAlign: "baseline" }}>
                          {row.chunk_index}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {toast && <Toast message={toast.message} danger={toast.danger} />}
    </AppChrome>
  );
}
