// Thin client for the privileged FastAPI tier (plan §4). Every mutation and
// door proof goes here; Supabase is only read directly (RLS + Realtime).

import { type AppSession, saveSession } from "./session";

interface MintedSessionWire {
  access_token: string;
  token_type: string;
  expires_at: string;
  user_id: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly reason: string,
  ) {
    super(`API ${status}: ${reason}`);
  }
}

function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) throw new Error("NEXT_PUBLIC_API_BASE_URL is not configured");
  return base.replace(/\/$/, "");
}

async function readDetail(response: Response): Promise<string> {
  // detail is not always a string (panel finding): FastAPI validation errors
  // carry an array, which would ride into React children and crash a render.
  return response
    .json()
    .then((data: { detail?: unknown }) =>
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail ?? "unknown").slice(0, 300),
    )
    .catch(() => "unknown");
}

async function postJson<T>(path: string, body: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(response.status, await readDetail(response));
  return (await response.json()) as T;
}

async function getJson<T>(path: string, token?: string): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBase()}${path}`, { method: "GET", headers });
  if (!response.ok) throw new ApiError(response.status, await readDetail(response));
  return (await response.json()) as T;
}

function toSession(wire: MintedSessionWire): AppSession {
  return {
    accessToken: wire.access_token,
    expiresAt: wire.expires_at,
    userId: wire.user_id,
  };
}

export async function telegramLogin(initData: string): Promise<AppSession> {
  const wire = await postJson<MintedSessionWire>("/auth/telegram", { init_data: initData });
  const session = toSession(wire);
  saveSession(session);
  return session;
}

export async function emailExchange(supabaseAccessToken: string): Promise<AppSession> {
  const wire = await postJson<MintedSessionWire>("/auth/email/exchange", {
    supabase_access_token: supabaseAccessToken,
  });
  const session = toSession(wire);
  saveSession(session);
  return session;
}

// ---------------------------------------------------------------- projects

export interface ProjectView {
  id: string;
  title: string;
  project_type: string;
  status: string;
}

export function createProject(
  title: string,
  token: string,
  language = "uz",
): Promise<ProjectView> {
  return postJson<ProjectView>("/projects", { title, language }, token);
}

// ----------------------------------------------------------------- sources

export interface PresignView {
  storage_key: string;
  upload_url: string;
  content_type: string;
  expires_in: number;
}

export interface SourceView {
  id: string;
  project_id: string;
  filename: string;
  file_type: string;
  file_size_bytes: number;
  storage_key: string;
}

export function presignUpload(
  projectId: string,
  filename: string,
  sizeBytes: number,
  token: string,
): Promise<PresignView> {
  return postJson<PresignView>(
    "/sources/presign",
    { project_id: projectId, filename, size_bytes: sizeBytes },
    token,
  );
}

// The browser PUTs the bytes straight to R2 with the presigned URL; the
// Content-Type must match what the presign signed or R2 rejects the request.
export async function uploadToR2(presign: PresignView, file: File): Promise<void> {
  const response = await fetch(presign.upload_url, {
    method: "PUT",
    headers: { "Content-Type": presign.content_type },
    body: file,
  });
  if (!response.ok) throw new ApiError(response.status, "r2_upload_failed");
}

export function registerSource(
  projectId: string,
  storageKey: string,
  filename: string,
  token: string,
): Promise<SourceView> {
  return postJson<SourceView>(
    "/sources",
    { project_id: projectId, storage_key: storageKey, filename },
    token,
  );
}

// -------------------------------------------------------------------- jobs

export interface JobView {
  id: string;
  project_id: string;
  job_type: string;
  status: string;
  progress: { step?: string; current?: number; total?: number };
  error_message: string | null;
  existing: boolean;
}

export function enqueueJob(
  projectId: string,
  sources: Array<{ storage_key: string; filename: string }>,
  token: string,
  // No client-side default: an omitted package means "charge the tier this
  // project already committed to", which only the server can resolve.
  // JSON.stringify drops the undefined key, so the body carries no package.
  packageName?: string,
  language = "uz",
): Promise<JobView> {
  return postJson<JobView>(
    "/jobs",
    { project_id: projectId, package: packageName, sources, language },
    token,
  );
}

export function getJob(jobId: string, token: string): Promise<JobView> {
  return getJson<JobView>(`/jobs/${jobId}`, token);
}

// -------------------------------------------------------- deck & sharing

export interface DeckAccessView {
  html_url: string;
  html_expires_in: number;
  downloads: Array<{ format: string; url: string; expires_in: number }>;
}

export function getDeckAccess(projectId: string, token: string): Promise<DeckAccessView> {
  return getJson<DeckAccessView>(`/projects/${projectId}/deck`, token);
}

export interface ShareView {
  share_token: string | null;
}

export function manageShare(
  projectId: string,
  action: "enable" | "rotate" | "disable",
  token: string,
): Promise<ShareView> {
  return postJson<ShareView>(`/projects/${projectId}/share`, { action }, token);
}

export interface SharedDeckView {
  title: string;
  html_url: string;
  expires_in: number;
}

export function resolveSharedDeck(shareToken: string): Promise<SharedDeckView> {
  return getJson<SharedDeckView>(`/public/decks/${shareToken}`);
}

// -------------------------------------------------------------- provenance

export interface ProvenanceRow {
  claim_text: string;
  quote: string | null;
  strength: string;
  source_filename: string | null;
  chunk_index: number | null;
}

export interface ProvenanceView {
  rows: ProvenanceRow[];
  total_claims: number;
}

export function getProvenance(projectId: string, token: string): Promise<ProvenanceView> {
  return getJson<ProvenanceView>(`/projects/${projectId}/provenance`, token);
}
