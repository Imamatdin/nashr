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

// No request may hang forever: a fetch with no AbortSignal is exactly how the
// "eternal skeleton" states happen — the UI cannot distinguish a slow network
// from a dead one, so it shows a spinner until the tab is closed.
const REQUEST_TIMEOUT_MS = 20_000;

async function request<T>(
  path: string,
  init: RequestInit,
  token?: string,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers: Record<string, string> = { ...((init.headers as Record<string, string>) ?? {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    if (!response.ok) throw new ApiError(response.status, await readDetail(response));
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

async function postJson<T>(path: string, body: unknown, token?: string): Promise<T> {
  return request<T>(
    path,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    token,
  );
}

async function getJson<T>(path: string, token?: string): Promise<T> {
  return request<T>(path, { method: "GET" }, token);
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

export interface LinkTelegramResult {
  /** True when a separate Telegram-side account was folded into this one. */
  merged: boolean;
  session: AppSession;
}

/**
 * Attach a proven Telegram identity to the signed-in user (G26).
 *
 * A person who paid inside the bot and then signed in with Google on the web
 * holds two accounts: one folio and balance in each. This is the merge — but it
 * needs initData, which only exists inside the Telegram Mini App webview, so
 * the only place it can be offered is a page opened from Telegram.
 *
 * The response re-mints the session for the SAME user; saving it keeps the
 * caller on a fresh token after the merge.
 */
export async function linkTelegram(initData: string, token: string): Promise<LinkTelegramResult> {
  const wire = await postJson<{ merged: boolean; session: MintedSessionWire }>(
    "/auth/link/telegram",
    { init_data: initData },
    token,
  );
  const session = toSession(wire.session);
  saveSession(session);
  return { merged: wire.merged, session };
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

/**
 * The same PUT, reporting bytes as they leave (G30).
 *
 * `fetch` cannot report upload progress — there is no readable stream for the
 * request body in any shipping browser — so a 20 MB file spends its whole life
 * behind an indeterminate "Yuklanmoqda…". XHR still exposes `upload.progress`,
 * which is the only reason this variant exists; `uploadToR2` above stays the
 * path for callers that do not draw a bar.
 */
export function uploadToR2WithProgress(
  presign: PresignView,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", presign.upload_url, true);
    // Must match what the presign signed, or R2 refuses the object.
    request.setRequestHeader("Content-Type", presign.content_type);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(1, event.loaded / event.total));
      }
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new ApiError(request.status, "r2_upload_failed"));
      }
    };
    request.onerror = () => reject(new ApiError(0, "r2_upload_failed"));
    request.ontimeout = () => reject(new ApiError(0, "r2_upload_failed"));
    request.onabort = () => reject(new ApiError(0, "r2_upload_failed"));
    request.send(file);
  });
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
  created_at: string | null;
  started_at: string | null;
  heartbeat_at: string | null;
  completed_at: string | null;
  /** The tier actually charged, authoritative over projects.package_tier. */
  package: string | null;
  deducted_amount: number | null;
  /** A FACT from the job-stamped ledger row, never inferred from timestamps. */
  refunded: boolean;
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
  // The typed topic finally reaches the generator (G1); answers carry the
  // interview when the user gave one (G2). Both are dropped from the body when
  // undefined, so an omitted answer set still means "decide for me".
  topic?: string,
  answers?: Record<string, unknown>,
): Promise<JobView> {
  return postJson<JobView>(
    "/jobs",
    { project_id: projectId, package: packageName, sources, language, topic, answers },
    token,
  );
}

/**
 * The project's latest generation job, whatever its status — the route that
 * lets a returning user see a run they no longer hold a `?job=` for (G3/G5).
 * 404 means "this project has never been generated", which is a STATE, not an
 * error; callers map it to `no_job`.
 */
export function getLatestJob(projectId: string, token: string): Promise<JobView> {
  return getJson<JobView>(`/jobs?project_id=${encodeURIComponent(projectId)}`, token);
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
  /** SIGNED-URL lifetime in seconds — NOT the share link's, which never expires. */
  expires_in: number;
  downloads: Array<{ format: string; url: string; expires_in: number }>;
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

// ----------------------------------------------------------------- session

export interface MintedSessionView {
  access_token: string;
  expires_at: string;
  user_id: string;
}

/**
 * Slide the session forward. A sliding window, not a refresh token: this needs
 * a token that is still VALID, so it cannot rescue an already-expired one. The
 * client must therefore refresh proactively (see lib/session.ts); a
 * 401-triggered attempt is a fallback that will usually fail.
 */
export async function refreshSession(token: string): Promise<AppSession> {
  const wire = await postJson<MintedSessionWire>("/auth/refresh", {}, token);
  const session = toSession(wire);
  saveSession(session);
  return session;
}

// ----------------------------------------------------------------- credits

export interface BalanceView {
  balance: number;
  currency: string;
}

export interface LedgerEntryView {
  id: string;
  amount: number;
  action: "grant_free" | "grant_paid" | "deduct_article" | "deduct_presentation" | "refund";
  reason: string;
  project_id: string | null;
  generation_job_id: string | null;
  created_at: string;
}

export interface LedgerView {
  balance: number;
  entries: LedgerEntryView[];
}

export function getBalance(token: string): Promise<BalanceView> {
  return getJson<BalanceView>("/credits", token);
}

export function getLedger(token: string, limit = 25): Promise<LedgerView> {
  return getJson<LedgerView>(`/credits/ledger?limit=${limit}`, token);
}

export interface PricingEntryView {
  package: string;
  price: number;
  ai_images: number;
  fix_allowance: number;
}

export interface PricingView {
  currency: string;
  packages: PricingEntryView[];
  free_credit_value: number;
  free_daily_cap: number;
  free_weekly_cap: number;
  free_project_cap: number;
}

/** Server truth for prices, image budgets and edit allowances. Unauthenticated. */
export function getPricing(): Promise<PricingView> {
  return getJson<PricingView>("/pricing");
}

// --------------------------------------------------------------- interview

export interface InterviewOptionView {
  value: string;
  label: string;
  is_default: boolean;
}

export interface InterviewQuestionView {
  question_id: string;
  question_text: string;
  question_type: string;
  options: InterviewOptionView[] | null;
  min_value: number | null;
  max_value: number | null;
  default_value: string | number | null;
  placeholder: string | null;
  help_text: string | null;
}

export interface InterviewView {
  questions: InterviewQuestionView[];
  detected_domain: string;
  estimated_slide_count: number;
  available_stats_count: number;
  available_people_count: number;
}

/**
 * The source-derived clarification set. 409 `sources_not_ready` is the normal
 * answer on a FIRST run — sources are processed during generation, so the
 * questions exist from the second run on. Callers treat that as "offer to
 * decide for them", never as an error.
 */
export function getInterview(
  projectId: string,
  token: string,
  language = "uz",
): Promise<InterviewView> {
  return postJson<InterviewView>(`/projects/${projectId}/interview`, { language }, token);
}

// -------------------------------------------------------------------- chat

export interface ChatFixView {
  slide_id: string;
  instruction: string;
}

export interface ChatPendingView {
  reason: string;
  fixes: ChatFixView[];
}

export interface ChatMessageView {
  role: "user" | "assistant";
  text: string;
}

export interface ChatHistoryView {
  can_edit: boolean;
  messages: ChatMessageView[];
  pending_action: ChatPendingView | null;
  fixes_used: number;
  fix_limit: number;
  fixes_remaining: number;
  package: string | null;
  slide_count: number;
  /** An edit job is re-rendering the deck right now. */
  applying_job_id: string | null;
}

export interface ChatTurnView {
  kind: "reply" | "approval_required" | "fix_ready";
  reply: string | null;
  pending_action: ChatPendingView | null;
  /** Present for `fix_ready`: the presentation_edit job to watch. */
  job_id: string | null;
  fixes_used: number;
  fix_limit: number;
  fixes_remaining: number;
}

export function getChat(projectId: string, token: string): Promise<ChatHistoryView> {
  return getJson<ChatHistoryView>(`/projects/${projectId}/chat`, token);
}

/**
 * One brain turn. A plain answer returns inline; an edit the user asked for
 * comes back as `fix_ready` with a job id. Never charges — editing a deck the
 * user already paid for is not a second sale.
 *
 * The turn calls a model, so it is slower than any other request here.
 */
export function postChat(
  projectId: string,
  message: string,
  token: string,
): Promise<ChatTurnView> {
  return request<ChatTurnView>(
    `/projects/${projectId}/chat`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) },
    token,
    90_000,
  );
}

export function approvePending(projectId: string, token: string): Promise<ChatTurnView> {
  return postJson<ChatTurnView>(`/projects/${projectId}/chat/approve`, {}, token);
}

export function rejectPending(projectId: string, token: string): Promise<ChatTurnView> {
  return postJson<ChatTurnView>(`/projects/${projectId}/chat/reject`, {}, token);
}
