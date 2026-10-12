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
  const headers: Record<string, string> = {
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    if (!response.ok)
      throw new ApiError(response.status, await readDetail(response));
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

async function postJson<T>(
  path: string,
  body: unknown,
  token?: string,
): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
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
  const wire = await postJson<MintedSessionWire>("/auth/telegram", {
    init_data: initData,
  });
  const session = toSession(wire);
  saveSession(session);
  return session;
}

export async function emailExchange(
  supabaseAccessToken: string,
): Promise<AppSession> {
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
export async function linkTelegram(
  initData: string,
  token: string,
): Promise<LinkTelegramResult> {
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
  projectType: "presentation" | "article" = "presentation",
): Promise<ProjectView> {
  return postJson<ProjectView>(
    "/projects",
    { title, language, project_type: projectType },
    token,
  );
}

export type ArticleBlockType = "paragraph" | "heading" | "quote" | "bullet";
export interface ArticleCitation {
  source_id: string;
  claim_id?: string | null;
  passage_id?: string | null;
  label: string;
}
export interface ArticleBlock {
  id: string;
  type: ArticleBlockType;
  text: string;
  level: number | null;
  citations: ArticleCitation[];
}
export interface ArticleContent {
  kind: "article";
  schema_version: 1;
  title: string;
  blocks: ArticleBlock[];
}
export interface ArticleDocumentView {
  document_id: string;
  revision_id: string;
  content: ArticleContent;
  updated_at: string;
}
export type RevisionKind =
  | "generation"
  | "regeneration"
  | "manual"
  | "autosave"
  | "ai_edit"
  | "bot_edit"
  | "import"
  | "restore";
/** A human save: an explicit one, or the debounced editor autosave. */
export type SaveKind = "manual" | "autosave";
export interface DocumentRevision {
  id: string;
  parent_revision_id: string | null;
  created_by: string | null;
  actor: string;
  kind: RevisionKind;
  schema_version: number;
  content_sha256: string;
  created_at: string;
  accepted_from_proposal_id: string | null;
}

export function initializeArticle(
  projectId: string,
  title: string,
  idempotencyKey: string,
  token: string,
): Promise<ArticleDocumentView> {
  return postJson<ArticleDocumentView>(
    `/projects/${projectId}/documents/article`,
    { title, idempotency_key: idempotencyKey },
    token,
  );
}
export function getArticle(
  projectId: string,
  token: string,
): Promise<ArticleDocumentView> {
  return getJson<ArticleDocumentView>(
    `/projects/${projectId}/documents/article`,
    token,
  );
}
export async function downloadArticleDocx(
  projectId: string,
  token: string,
  revisionId: string,
): Promise<Blob> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(
      `${apiBase()}/projects/${projectId}/documents/article/export.docx?revision_id=${encodeURIComponent(revisionId)}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      },
    );
    if (!response.ok)
      throw new ApiError(response.status, await readDetail(response));
    return await response.blob();
  } finally {
    clearTimeout(timer);
  }
}
export function saveArticle(
  projectId: string,
  baseRevisionId: string,
  content: ArticleContent,
  idempotencyKey: string,
  token: string,
  kind: SaveKind = "autosave",
): Promise<ArticleDocumentView> {
  return request<ArticleDocumentView>(
    `/projects/${projectId}/documents/article`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_revision_id: baseRevisionId,
        idempotency_key: idempotencyKey,
        content,
        kind,
      }),
    },
    token,
  );
}
export function getArticleRevisions(
  projectId: string,
  token: string,
): Promise<{ revisions: DocumentRevision[] }> {
  return getJson<{ revisions: DocumentRevision[] }>(
    `/projects/${projectId}/documents/article/revisions`,
    token,
  );
}
export function restoreArticle(
  projectId: string,
  revisionId: string,
  baseRevisionId: string,
  idempotencyKey: string,
  token: string,
): Promise<ArticleDocumentView> {
  return postJson<ArticleDocumentView>(
    `/projects/${projectId}/documents/article/restore`,
    {
      revision_id: revisionId,
      base_revision_id: baseRevisionId,
      idempotency_key: idempotencyKey,
    },
    token,
  );
}

export interface DesignPalette {
  background: string;
  surface: string;
  text: string;
  accent: string;
  text_secondary: string;
}
export interface DesignSlideContent {
  title: string;
  subtitle?: string | null;
  body_text?: string | null;
  bullets?: string[] | null;
  quote_text?: string | null;
  quote_attribution?: string | null;
  speaker_notes?: string | null;
  stats?: Array<{ value: string; unit?: string; label: string }> | null;
  background_url?: string | null;
  [key: string]: unknown;
}
export interface DesignSlide {
  slide_id: string;
  slide_index: number;
  slide_type: string;
  content: DesignSlideContent;
  accent_override?: string | null;
  [key: string]: unknown;
}
export interface DesignDeck {
  project_id: string;
  title: string;
  subtitle?: string | null;
  language: string;
  design: {
    palette: DesignPalette;
    heading_font: string;
    body_font: string;
    [key: string]: unknown;
  };
  slides: DesignSlide[];
  [key: string]: unknown;
}
export interface DesignDocumentView {
  document_id: string;
  revision_id: string;
  content: DesignDeck;
  updated_at: string;
}
export interface DesignRenderView {
  // null when every format was already registered: nothing to render.
  job_id: string | null;
  formats: string[];
  status: string;
  existing: boolean;
  revision_id: string;
  renderer_version: string;
}

export function getDesign(
  projectId: string,
  token: string,
): Promise<DesignDocumentView> {
  return getJson<DesignDocumentView>(`/projects/${projectId}/design`, token);
}
export function saveDesign(
  projectId: string,
  baseRevisionId: string,
  content: DesignDeck,
  idempotencyKey: string,
  token: string,
  kind: SaveKind = "autosave",
): Promise<DesignDocumentView> {
  return request<DesignDocumentView>(
    `/projects/${projectId}/design`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_revision_id: baseRevisionId,
        idempotency_key: idempotencyKey,
        content,
        kind,
      }),
    },
    token,
  );
}
export function getDesignRevisions(
  projectId: string,
  token: string,
): Promise<{ revisions: DocumentRevision[] }> {
  return getJson<{ revisions: DocumentRevision[] }>(
    `/projects/${projectId}/design/revisions`,
    token,
  );
}
export function restoreDesign(
  projectId: string,
  revisionId: string,
  baseRevisionId: string,
  idempotencyKey: string,
  token: string,
): Promise<DesignDocumentView> {
  return postJson<DesignDocumentView>(
    `/projects/${projectId}/design/restore`,
    {
      revision_id: revisionId,
      base_revision_id: baseRevisionId,
      idempotency_key: idempotencyKey,
    },
    token,
  );
}
export function renderDesign(
  projectId: string,
  revisionId: string,
  token: string,
): Promise<DesignRenderView> {
  return postJson<DesignRenderView>(
    `/projects/${projectId}/design/render`,
    { revision_id: revisionId },
    token,
  );
}

// ----------------------------------------------------------------- sources

export interface PresignView {
  storage_key: string;
  upload_url: string;
  content_type: string;
  expires_in: number;
}

export interface EvidencePassage {
  id: string;
  source_id: string;
  project_id: string;
  chunk_index: number;
  text: string;
  page: number | null;
  is_ocr: boolean;
  confidence: number;
  created_at: string;
}
export interface EvidenceSource {
  id: string;
  filename: string;
  processed_at: string | null;
  passage_count: number;
  warnings: string[];
}
export interface EvidenceView {
  sources: EvidenceSource[];
  passages: EvidencePassage[];
  next_offset: number | null;
  job: JobView | null;
}
export function getEvidence(projectId: string, token: string, sourceId = "", offset = 0): Promise<EvidenceView> {
  const query = new URLSearchParams({ offset: String(offset) });
  if (sourceId) query.set("source_id", sourceId);
  return getJson<EvidenceView>(`/projects/${projectId}/evidence?${query}`, token);
}
export function processEvidence(projectId: string, token: string): Promise<JobView> {
  return postJson<JobView>(`/projects/${projectId}/evidence/process`, {}, token);
}
export function getEvidencePassage(projectId: string, passageId: string, token: string): Promise<EvidencePassage> {
  return getJson<EvidencePassage>(`/projects/${projectId}/evidence/passages/${passageId}`, token);
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
export async function uploadToR2(
  presign: PresignView,
  file: File,
): Promise<void> {
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
  progress: { step?: string; current?: number; total?: number; failed_sources?: string[] };
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
    {
      project_id: projectId,
      package: packageName,
      sources,
      language,
      topic,
      answers,
    },
    token,
  );
}

/**
 * The project's latest generation job, whatever its status — the route that
 * lets a returning user see a run they no longer hold a `?job=` for (G3/G5).
 * 404 means "this project has never been generated", which is a STATE, not an
 * error; callers map it to `no_job`.
 */
export function getLatestJob(
  projectId: string,
  token: string,
): Promise<JobView> {
  return getJson<JobView>(
    `/jobs?project_id=${encodeURIComponent(projectId)}`,
    token,
  );
}

export function getJob(jobId: string, token: string): Promise<JobView> {
  return getJson<JobView>(`/jobs/${jobId}`, token);
}

// -------------------------------------------------------- deck & sharing

/** Signed URLs for one (revision, renderer) export set. */
export interface ExportLinks {
  revision_id: string;
  renderer_version: string;
  created_at: string;
  html_url: string | null;
  html_expires_in: number;
  downloads: Array<{ format: string; url: string; expires_in: number }>;
}
/** An export set that is NOT the requested one; the UI must label it. */
export interface FallbackExport extends ExportLinks {
  reason: "older_renderer" | "older_revision";
}
/**
 * Downloads are keyed by revision (ADR 0001). `current` is the requested
 * revision rendered by today's renderer; when it is missing the state is
 * `render_needed`, and any `fallback` is an older export, never the head's.
 */
export interface DeckAccessView {
  revision_id: string;
  head_revision_id: string;
  is_head: boolean;
  // partial: the current renderer made some of the required formats only.
  state: "ready" | "partial" | "render_needed";
  renderer_version: string;
  required_formats: string[];
  available_formats: string[];
  missing_formats: string[];
  current: ExportLinks | null;
  fallback: FallbackExport | null;
}

export function getDeckAccess(
  projectId: string,
  token: string,
  revisionId?: string,
): Promise<DeckAccessView> {
  const query = revisionId ? `?revision_id=${encodeURIComponent(revisionId)}` : "";
  return getJson<DeckAccessView>(`/projects/${projectId}/deck${query}`, token);
}

// ----------------------------------------------------------------- proposals

export interface ProposalView {
  id: string;
  kind: RevisionKind;
  status: "pending" | "accepted" | "rejected" | "superseded";
  base_revision_id: string | null;
  created_at: string;
}
export interface DiffEntry {
  item_id: string;
  change: "added" | "removed" | "changed" | "moved";
  label: string;
  before_index: number | null;
  after_index: number | null;
}
export interface RevisionDiff {
  unit: "slide" | "block";
  entries: DiffEntry[];
  fields_changed: string[];
}
export interface ProposalDiffView {
  proposal: ProposalView;
  /** The head this diff was computed against; accept must send it back. */
  head_revision_id: string | null;
  ai_changes: RevisionDiff;
  accept_changes: RevisionDiff;
  schema_matches_head: boolean;
}

export function listProposals(
  projectId: string,
  token: string,
): Promise<{ head_revision_id: string | null; proposals: ProposalView[] }> {
  return getJson(`/projects/${projectId}/proposals`, token);
}
export function getProposalDiff(
  projectId: string,
  proposalId: string,
  token: string,
): Promise<ProposalDiffView> {
  return getJson<ProposalDiffView>(`/projects/${projectId}/proposals/${proposalId}/diff`, token);
}
export function acceptProposal(
  projectId: string,
  proposalId: string,
  expectedHeadRevisionId: string | null,
  idempotencyKey: string,
  token: string,
): Promise<{ status: string; revision_id: string | null; head_revision_id: string | null }> {
  return postJson(
    `/projects/${projectId}/proposals/${proposalId}/accept`,
    { expected_head_revision_id: expectedHeadRevisionId, idempotency_key: idempotencyKey },
    token,
  );
}
export function rejectProposal(
  projectId: string,
  proposalId: string,
  token: string,
): Promise<ProposalView> {
  return postJson<ProposalView>(`/projects/${projectId}/proposals/${proposalId}/reject`, {}, token);
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
  source_id?: string | null;
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

export function getProvenance(
  projectId: string,
  token: string,
): Promise<ProvenanceView> {
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
  action:
    | "grant_free"
    | "grant_paid"
    | "deduct_article"
    | "deduct_presentation"
    | "refund";
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
  return postJson<InterviewView>(
    `/projects/${projectId}/interview`,
    { language },
    token,
  );
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

export function getChat(
  projectId: string,
  token: string,
): Promise<ChatHistoryView> {
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
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
    token,
    90_000,
  );
}

export function approvePending(
  projectId: string,
  token: string,
): Promise<ChatTurnView> {
  return postJson<ChatTurnView>(
    `/projects/${projectId}/chat/approve`,
    {},
    token,
  );
}

export function rejectPending(
  projectId: string,
  token: string,
): Promise<ChatTurnView> {
  return postJson<ChatTurnView>(
    `/projects/${projectId}/chat/reject`,
    {},
    token,
  );
}

// --------------------------------------------------------------- decisions

export interface DecisionSectionView {
  section_name: string;
  thesis: string;
  phase: string;
}

export interface ResearchPaper {
  title: string;
  authors: string[];
  year: number | null;
  abstract: string | null;
  doi: string | null;
  citation_count: number | null;
  pdf_url: string | null;
  source_api: string;
  external_id: string;
  journal: string | null;
}
export interface ResearchView {
  papers: ResearchPaper[];
  unavailable_providers: string[];
  lex_uz_available: boolean;
}
export function searchResearch(
  projectId: string,
  query: string,
  token: string,
): Promise<ResearchView> {
  return postJson<ResearchView>(
    `/projects/${projectId}/research`,
    { query },
    token,
  );
}

export interface DecisionsView {
  title: string;
  language: string;
  /** Null for a deck generated before the planner became binding. */
  thesis: string | null;
  audience_takeaway: string | null;
  sections: DecisionSectionView[];
  mood: string;
  palette: {
    background: string;
    surface: string;
    text: string;
    accent: string;
    text_secondary: string;
  };
  heading_font: string;
  body_font: string;
  background_treatment: string;
  image_style_prefix: string;
  image_cohesion_note: string | null;
  audience: string;
  talk_duration_minutes: number;
  narrative_emphasis: string;
  include_interactive: boolean;
  slide_count: number;
  slides: Array<{
    slide_number: number;
    slide_id: string;
    slide_type: string;
    title: string;
  }>;
}

/**
 * What the pipeline DECIDED — the argument, the look, and the roster.
 *
 * All of it has been persisted in decks.deck_json since the pipeline shipped
 * and had no read route, so the workspace could only repeat step labels (G14).
 */
export function getDecisions(
  projectId: string,
  token: string,
): Promise<DecisionsView> {
  return getJson<DecisionsView>(`/projects/${projectId}/decisions`, token);
}
