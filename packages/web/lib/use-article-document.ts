"use client";

// Article load/save/recovery state. Edits are mirrored to a device draft until
// the server confirms them; an in-flight save keeps its idempotency key until its
// outcome is known, so a retry after a lost response replays rather than conflicts.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError, getArticle, initializeArticle, restoreArticle, saveArticle,
  type ArticleContent, type ArticleDocumentView,
} from "./api";
import {
  clearDraft, readDraft, reconcileDraft, writeDraft, type DraftStorage, type PendingSave,
} from "./article-draft";
import { newBlock } from "./article-editor";
import { useAppSession } from "./use-session";

export type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict" | "rejected";
export type LoadState = { kind: "loading" } | { kind: "ready" } | { kind: "failed"; hasDraft: boolean };
export type Recovery = { kind: "resumed"; at: string } | { kind: "conflict"; at: string | null } | null;

const SAVE_DELAY_MS = 900;
const MAX_RETRY_MS = 30_000;

function deviceStorage(): DraftStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function editable(view: ArticleDocumentView): ArticleContent {
  return view.content.blocks.length
    ? view.content
    : { ...view.content, blocks: [newBlock("heading"), newBlock("paragraph")] };
}

export function useArticleDocument(projectId: string, title: string) {
  const { session, withAuth } = useAppSession();
  const userId = session?.userId ?? null;
  const [document, setDocument] = useState<ArticleDocumentView | null>(null);
  const [content, setContent] = useState<ArticleContent | null>(null);
  const [state, setState] = useState<SaveState>("saved");
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [recovery, setRecovery] = useState<Recovery>(null);
  const [deviceCopy, setDeviceCopy] = useState(true);
  const [retryAttempt, setRetryAttempt] = useState(0);
  const contentRef = useRef<ArticleContent | null>(null);
  const documentRef = useRef<ArticleDocumentView | null>(null);
  const pendingRef = useRef<PendingSave | null>(null);
  const savingRef = useRef(false);
  contentRef.current = content;
  documentRef.current = document;

  const persist = useCallback((next: ArticleContent, baseRevisionId: string) => {
    const storage = deviceStorage();
    if (!userId) return;
    const kept = storage !== null && writeDraft(storage, {
      v: 1, userId, projectId, baseRevisionId, content: next,
      updatedAt: new Date().toISOString(), pending: pendingRef.current,
    });
    setDeviceCopy(kept);
  }, [projectId, userId]);

  const forget = useCallback(() => {
    const storage = deviceStorage();
    if (storage && userId) clearDraft(storage, userId, projectId);
    pendingRef.current = null;
    setDeviceCopy(true);
  }, [projectId, userId]);

  const adopt = useCallback((view: ArticleDocumentView, next: ArticleContent, nextState: SaveState) => {
    documentRef.current = view;
    contentRef.current = next;
    setDocument(view);
    setContent(next);
    setState(nextState);
  }, []);

  const open = useCallback(async () => {
    if (!userId) return;
    setLoad({ kind: "loading" });
    const storage = deviceStorage();
    const draft = storage ? readDraft(storage, userId, projectId) : null;
    let view: ArticleDocumentView | null;
    try {
      view = await withAuth(async (token) => {
        try {
          return await getArticle(projectId, token);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            return initializeArticle(projectId, title, `init:${projectId}`, token);
          }
          throw error;
        }
      });
    } catch {
      setLoad({ kind: "failed", hasDraft: draft !== null });
      return;
    }
    if (!view) return;
    let base = draft?.baseRevisionId;
    const pending = draft?.pending;
    if (draft && pending && pending.baseRevisionId !== view.revision_id) {
      // The server moved: find out whether it moved because our own save landed.
      const replayed = await withAuth((token) =>
        saveArticle(projectId, pending.baseRevisionId, pending.content, pending.key, token),
      ).catch(() => null);
      if (replayed?.revision_id === view.revision_id) base = view.revision_id;
    }
    const outcome = reconcileDraft(view, draft && base ? { ...draft, baseRevisionId: base } : draft);
    pendingRef.current = null;
    if (outcome.kind === "none") {
      forget();
      const initial = editable(view);
      adopt(view, initial, initial === view.content ? "saved" : "dirty");
      setRecovery(null);
    } else {
      adopt(view, outcome.draft.content, outcome.kind === "resume" ? "dirty" : "conflict");
      persist(outcome.draft.content, outcome.kind === "resume" ? view.revision_id : outcome.draft.baseRevisionId);
      setRecovery(outcome.kind === "resume"
        ? { kind: "resumed", at: outcome.draft.updatedAt }
        : { kind: "conflict", at: outcome.draft.updatedAt });
    }
    setLoad({ kind: "ready" });
  }, [adopt, forget, persist, projectId, title, userId, withAuth]);

  useEffect(() => {
    void open();
  }, [open]);

  const save = useCallback(async () => {
    const current = contentRef.current;
    const base = documentRef.current;
    if (!current || !base || !current.title.trim() || savingRef.current) return;
    if (!pendingRef.current || pendingRef.current.baseRevisionId !== base.revision_id) {
      pendingRef.current = { key: crypto.randomUUID(), baseRevisionId: base.revision_id, content: current };
    }
    const attempt = pendingRef.current;
    persist(current, base.revision_id);
    savingRef.current = true;
    setState("saving");
    try {
      const next = await withAuth((token) =>
        saveArticle(projectId, attempt.baseRevisionId, attempt.content, attempt.key, token),
      );
      if (!next) {
        setState("error");
        return;
      }
      pendingRef.current = null;
      setRetryAttempt(0);
      const latest = contentRef.current ?? attempt.content;
      if (sameJson(latest, attempt.content)) {
        forget();
        adopt(next, next.content, "saved");
      } else {
        documentRef.current = next;
        setDocument(next);
        persist(latest, next.revision_id);
        setState("dirty");
      }
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 409 || status === 422) pendingRef.current = null;
      persist(contentRef.current ?? current, base.revision_id);
      setState(status === 409 ? "conflict" : status === 422 ? "rejected" : "error");
      if (status === 409) setRecovery({ kind: "conflict", at: null });
      if (status !== 409 && status !== 422) setRetryAttempt((n) => n + 1);
    } finally {
      savingRef.current = false;
    }
  }, [adopt, forget, persist, projectId, withAuth]);

  useEffect(() => {
    if (state !== "dirty" || load.kind !== "ready") return;
    const timer = window.setTimeout(() => void save(), SAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [content, load.kind, save, state]);

  useEffect(() => {
    if (state !== "error") return;
    const delay = Math.min(MAX_RETRY_MS, 2_000 * 2 ** Math.max(0, retryAttempt - 1));
    const timer = window.setTimeout(() => void save(), delay);
    const online = () => void save();
    window.addEventListener("online", online);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("online", online);
    };
  }, [retryAttempt, save, state]);

  const unsafeToLeave = state !== "saved" && !deviceCopy;
  useEffect(() => {
    if (!unsafeToLeave) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsafeToLeave]);

  const update = useCallback((next: ArticleContent) => {
    const base = documentRef.current;
    contentRef.current = next;
    setContent(next);
    if (base) persist(next, base.revision_id);
    setState((previous) => (previous === "conflict" ? previous : "dirty"));
  }, [persist]);

  async function head(): Promise<ArticleDocumentView | null> {
    try {
      return await withAuth((token) => getArticle(projectId, token));
    } catch {
      setState("error");
      return null;
    }
  }

  /** Commit the local version on top of whatever is current; the other version stays in history. */
  async function keepMine() {
    const latest = await head();
    const mine = contentRef.current;
    if (!latest || !mine) return;
    pendingRef.current = null;
    documentRef.current = latest;
    setDocument(latest);
    persist(mine, latest.revision_id);
    setRecovery(null);
    setState("dirty");
  }

  /** Drop the device copy and continue from the server's current revision. */
  async function takeSaved() {
    const latest = await head();
    if (!latest) return;
    forget();
    setRecovery(null);
    adopt(latest, editable(latest), "saved");
  }

  async function restore(revisionId: string): Promise<"ok" | "blocked" | "failed"> {
    const base = documentRef.current;
    if (!base || state !== "saved" || savingRef.current) return "blocked";
    savingRef.current = true;
    try {
      const view = await withAuth((token) =>
        restoreArticle(projectId, revisionId, base.revision_id, crypto.randomUUID(), token),
      );
      if (!view) return "failed";
      forget();
      adopt(view, view.content, "saved");
      return "ok";
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setState("conflict");
        setRecovery({ kind: "conflict", at: null });
      }
      return "failed";
    } finally {
      savingRef.current = false;
    }
  }

  return {
    document, content, state, load, recovery, deviceCopy,
    update, retry: () => void save(), reopen: () => void open(),
    keepMine, takeSaved, dismissRecovery: () => setRecovery(null), restore,
  };
}
