import { describe, expect, it } from "vitest";
import type { ArticleContent, ArticleDocumentView } from "./api";
import {
  clearDraft, draftKey, readDraft, reconcileDraft, sameArticleContent, writeDraft, type ArticleDraft, type DraftStorage,
} from "./article-draft";

function memoryStorage(failWrites = false): DraftStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      if (failWrites) throw new DOMException("quota", "QuotaExceededError");
      data.set(key, value);
    },
    removeItem: (key) => void data.delete(key),
  };
}

const citation = { source_id: "s1", passage_id: "p1", claim_id: null, label: "a.pdf · 2" };
function content(text: string, label = citation.label): ArticleContent {
  return {
    kind: "article", schema_version: 1, title: "Orol",
    blocks: [{ id: "B1", type: "paragraph", text, level: null, citations: [{ ...citation, label }] }],
  };
}
function view(revision: string, text: string): ArticleDocumentView {
  return { document_id: "d", revision_id: revision, content: content(text), updated_at: "2026-09-30T00:00:00Z" };
}
function draft(base: string, text: string): ArticleDraft {
  return { v: 1, userId: "u1", projectId: "p1", baseRevisionId: base, content: content(text), updatedAt: "2026-09-30T00:00:00Z", pending: null };
}

describe("article draft storage", () => {
  it("round-trips a draft scoped to one user and project", () => {
    const storage = memoryStorage();
    expect(writeDraft(storage, draft("r1", "local"))).toBe(true);
    expect(readDraft(storage, "u1", "p1")?.content.blocks[0].text).toBe("local");
    expect(readDraft(storage, "u2", "p1")).toBeNull();
    expect(readDraft(storage, "u1", "p2")).toBeNull();
  });

  it("reports a refused write instead of claiming the draft is kept", () => {
    expect(writeDraft(memoryStorage(true), draft("r1", "local"))).toBe(false);
  });

  it("discards a corrupt or foreign record", () => {
    const storage = memoryStorage();
    storage.data.set(draftKey("u1", "p1"), "{not json");
    expect(readDraft(storage, "u1", "p1")).toBeNull();
    expect(storage.data.size).toBe(0);
    storage.data.set(draftKey("u1", "p1"), JSON.stringify({ ...draft("r1", "x"), userId: "u2" }));
    expect(readDraft(storage, "u1", "p1")).toBeNull();
  });

  it("clears only the addressed draft", () => {
    const storage = memoryStorage();
    writeDraft(storage, draft("r1", "a"));
    writeDraft(storage, { ...draft("r1", "b"), projectId: "p2" });
    clearDraft(storage, "u1", "p1");
    expect(readDraft(storage, "u1", "p1")).toBeNull();
    expect(readDraft(storage, "u1", "p2")?.content.blocks[0].text).toBe("b");
  });
});

describe("draft reconciliation", () => {
  it("ignores server label canonicalization and id case", () => {
    const server = content("same", "Canonical label");
    const local = { ...content("same"), blocks: [{ ...content("same").blocks[0], id: "b1" }] };
    expect(sameArticleContent(server, local)).toBe(true);
    expect(sameArticleContent(content("same"), content("changed"))).toBe(false);
  });

  it("drops a draft that already matches the server", () => {
    expect(reconcileDraft(view("r2", "saved"), draft("r1", "saved"))).toEqual({ kind: "none" });
  });

  it("resumes unsaved edits made on top of the current revision", () => {
    expect(reconcileDraft(view("r1", "server"), draft("r1", "local")).kind).toBe("resume");
  });

  it("asks the user when the server moved on after the draft's base", () => {
    expect(reconcileDraft(view("r2", "elsewhere"), draft("r1", "local")).kind).toBe("conflict");
  });
});
