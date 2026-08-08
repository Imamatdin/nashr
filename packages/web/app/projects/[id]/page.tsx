"use client";

// Project workspace (P3 item 2): upload sources, enqueue, watch progress by
// polling, then the delivered deck inline with downloads, share controls and
// the provenance table. Reads ride RLS (sources list); every mutation and
// signed-URL mint goes through the API.

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError,
  type DeckAccessView,
  type JobView,
  type ProvenanceView,
  type SourceView,
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

export default function ProjectPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const projectId = params.id;

  const [session, setSession] = useState<AppSession | null>(null);
  const [project, setProject] = useState<ProjectRow | null>(null);
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<JobView | null>(null);
  const [deck, setDeck] = useState<DeckAccessView | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceView | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const pollTimer = useRef<number | null>(null);

  const refreshSources = useCallback(
    (activeSession: AppSession) => {
      const supabase = createRlsClient(activeSession.accessToken);
      supabase
        .from("sources")
        .select("id,filename,file_type,storage_key")
        .eq("project_id", projectId)
        .order("created_at", { ascending: true })
        .then(({ data, error: queryError }) => {
          if (queryError) setError(queryError.message);
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
          setError(String(deckError));
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
      router.replace("/login");
      return;
    }
    setSession(active);
    const supabase = createRlsClient(active.accessToken);
    supabase
      .from("projects")
      .select("id,title,status,share_token")
      .eq("id", projectId)
      .single()
      .then(({ data, error: queryError }) => {
        if (queryError) setError(queryError.message);
        else {
          const row = data as ProjectRow;
          setProject(row);
          setShareToken(row.share_token);
        }
      });
    refreshSources(active);
    void loadDeck(active);
    return () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    };
  }, [projectId, router, refreshSources, loadDeck]);

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
            void loadDeck(activeSession);
          }
        })
        .catch((pollError) => setError(String(pollError)));
    },
    [loadDeck],
  );

  async function onUpload() {
    if (!session) return;
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const presign = await presignUpload(projectId, file.name, file.size, session.accessToken);
      await uploadToR2(presign, file);
      await registerSource(projectId, presign.storage_key, file.name, session.accessToken);
      if (fileInput.current) fileInput.current.value = "";
      refreshSources(session);
    } catch (uploadError) {
      setError(String(uploadError));
    } finally {
      setUploading(false);
    }
  }

  async function onEnqueue() {
    if (!session) return;
    setError(null);
    try {
      const view = await enqueueJob(
        projectId,
        sources.map((s) => ({ storage_key: s.storage_key, filename: s.filename })),
        session.accessToken,
      );
      setJob(view);
      pollJob(view.id, session);
    } catch (enqueueError) {
      setError(String(enqueueError));
    }
  }

  async function onShare(action: "enable" | "rotate" | "disable") {
    if (!session) return;
    setError(null);
    try {
      const view = await manageShare(projectId, action, session.accessToken);
      setShareToken(view.share_token);
    } catch (shareError) {
      setError(String(shareError));
    }
  }

  const running = job !== null && (job.status === "queued" || job.status === "processing");
  const progress = job?.progress ?? {};
  const shareUrl =
    shareToken && typeof window !== "undefined"
      ? `${window.location.origin}/p/${shareToken}`
      : null;

  return (
    <main>
      <h1>{project ? project.title : "Loyiha"}</h1>
      {error && <p style={{ color: "crimson" }}>Xato: {error}</p>}

      <h2>Manbalar</h2>
      {sources.length === 0 && <p>Hozircha manba yuklanmagan.</p>}
      <ul>
        {sources.map((s) => (
          <li key={s.id}>
            {s.filename} ({s.file_type})
          </li>
        ))}
      </ul>
      <p>
        <input ref={fileInput} type="file" accept=".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv" />
        <button onClick={() => void onUpload()} disabled={uploading}>
          {uploading ? "Yuklanmoqda…" : "Manba yuklash"}
        </button>
      </p>

      <h2>Generatsiya</h2>
      <p>
        <button onClick={() => void onEnqueue()} disabled={sources.length === 0 || running}>
          Taqdimot yaratish
        </button>
      </p>
      {job && (
        <p>
          Holat: {job.status}
          {running && progress.step && (
            <>
              {" — "}
              {progress.step} ({progress.current ?? 0}/{progress.total ?? 0})
              <progress value={progress.current ?? 0} max={progress.total ?? 1} />
            </>
          )}
          {job.status === "failed" && job.error_message && (
            <span style={{ color: "crimson" }}> — {job.error_message}</span>
          )}
        </p>
      )}

      {deck && (
        <>
          <h2>Taqdimot</h2>
          <iframe
            src={deck.html_url}
            sandbox="allow-scripts"
            style={{ width: "100%", aspectRatio: "16 / 9", border: "1px solid #ccc" }}
            title="Taqdimot"
          />
          <p>
            {deck.downloads.map((d) => (
              <a key={d.format} href={d.url} download style={{ marginRight: "1rem" }}>
                {d.format.toUpperCase()} yuklab olish
              </a>
            ))}
          </p>

          <h2>Ulashish</h2>
          {shareUrl ? (
            <p>
              <a href={shareUrl}>{shareUrl}</a>{" "}
              <button onClick={() => void onShare("rotate")}>Havolani yangilash</button>{" "}
              <button onClick={() => void onShare("disable")}>O&apos;chirish</button>
            </p>
          ) : (
            <p>
              <button onClick={() => void onShare("enable")}>Ommaviy havola yaratish</button>
            </p>
          )}
        </>
      )}

      {provenance && provenance.rows.length > 0 && (
        <>
          <h2>Dalillar (manbalarga bog&apos;lanish)</h2>
          <table border={1} cellPadding={6} style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Da&apos;vo</th>
                <th>Iqtibos</th>
                <th>Manba fayli</th>
                <th>Bo&apos;lak</th>
              </tr>
            </thead>
            <tbody>
              {provenance.rows.map((row, index) => (
                <tr key={index}>
                  <td>{row.claim_text}</td>
                  <td>{row.quote ?? "—"}</td>
                  <td>{row.source_filename ?? "—"}</td>
                  <td>{row.chunk_index ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
