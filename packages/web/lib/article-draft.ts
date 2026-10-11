// Device-local recovery for the article editor. The server revision stays the
// source of truth; this record only exists while local edits are not known to
// be on the server, and it is scoped to one user and one project.
import type { ArticleContent, ArticleDocumentView } from "./api";

export interface PendingSave {
  /** Reused on retry so a save that committed but lost its response replays instead of conflicting. */
  key: string;
  baseRevisionId: string;
  content: ArticleContent;
}

export interface ArticleDraft {
  v: 1;
  userId: string;
  projectId: string;
  baseRevisionId: string;
  content: ArticleContent;
  updatedAt: string;
  pending: PendingSave | null;
}

export type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type Reconciliation =
  | { kind: "none" }
  | { kind: "resume"; draft: ArticleDraft }
  | { kind: "conflict"; draft: ArticleDraft };

export function draftKey(userId: string, projectId: string): string {
  return `nashr.articleDraft.${userId}.${projectId}`;
}

function isContent(value: unknown): value is ArticleContent {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<ArticleContent>;
  return candidate.kind === "article" && typeof candidate.title === "string" && Array.isArray(candidate.blocks);
}

function isPending(value: unknown): value is PendingSave {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<PendingSave>;
  return typeof candidate.key === "string" && typeof candidate.baseRevisionId === "string" && isContent(candidate.content);
}

export function readDraft(storage: DraftStorage, userId: string, projectId: string): ArticleDraft | null {
  let raw: string | null;
  try {
    raw = storage.getItem(draftKey(userId, projectId));
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<ArticleDraft>;
    if (
      parsed.v === 1 && parsed.userId === userId && parsed.projectId === projectId &&
      typeof parsed.baseRevisionId === "string" && typeof parsed.updatedAt === "string" &&
      isContent(parsed.content) && (parsed.pending === null || isPending(parsed.pending))
    ) return parsed as ArticleDraft;
  } catch {
    // A corrupt record cannot be trusted as the user's work; fall through to discard it.
  }
  clearDraft(storage, userId, projectId);
  return null;
}

/** Returns false when the device refused the write (quota, private mode) so the UI can say so. */
export function writeDraft(storage: DraftStorage, draft: ArticleDraft): boolean {
  try {
    storage.setItem(draftKey(draft.userId, draft.projectId), JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}

export function clearDraft(storage: DraftStorage, userId: string, projectId: string): void {
  try {
    storage.removeItem(draftKey(userId, projectId));
  } catch {
    // Nothing further to do: an unremovable draft is re-validated against the server on the next load.
  }
}

/** Compares what the user wrote; server-canonicalized citation labels are not user edits. */
export function sameArticleContent(a: ArticleContent, b: ArticleContent): boolean {
  const shape = (content: ArticleContent) => JSON.stringify({
    title: content.title,
    blocks: content.blocks.map((block) => ({
      id: block.id.toLowerCase(), type: block.type, text: block.text, level: block.level ?? null,
      citations: block.citations.map((c) => [c.source_id, c.passage_id ?? null, c.claim_id ?? null]),
    })),
  });
  return shape(a) === shape(b);
}

export function reconcileDraft(server: ArticleDocumentView, draft: ArticleDraft | null): Reconciliation {
  if (!draft || sameArticleContent(server.content, draft.content)) return { kind: "none" };
  return draft.baseRevisionId === server.revision_id ? { kind: "resume", draft } : { kind: "conflict", draft };
}
