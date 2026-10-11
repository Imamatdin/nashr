import { describe, expect, it } from "vitest";
import { attachPassage, detachCitation, articleEvidenceRows } from "./article-evidence";
import type { ArticleContent, EvidencePassage } from "./api";

const content: ArticleContent = {
  kind: "article", schema_version: 1, title: "Research",
  blocks: [{ id: "b", type: "paragraph", level: null, text: "My conclusion", citations: [] }],
};
const passage: EvidencePassage = {
  id: "p", source_id: "s", project_id: "project", text: "Exact original text", page: 7,
  chunk_index: 1, is_ocr: false, confidence: 100, created_at: "2026-09-22",
};

describe("article evidence attachments", () => {
  it("attaches a passage without changing text or inventing a verified claim", () => {
    const next = attachPassage(content, "b", passage, "paper.pdf");
    expect(next.blocks[0].text).toBe("My conclusion");
    expect(next.blocks[0].citations).toEqual([
      { source_id: "s", passage_id: "p", claim_id: null, label: "paper.pdf · 7" },
    ]);
    expect(attachPassage(next, "b", passage, "paper.pdf")).toBe(next);
    expect(content.blocks[0].citations).toEqual([]);
  });
  it("does not move a citation to a different block when its target was deleted", () => {
    expect(attachPassage(content, "missing", passage, "paper.pdf")).toBe(content);
  });
  it("removes only the selected reference", () => {
    const next = attachPassage(content, "b", passage, "paper.pdf");
    expect(detachCitation(next, "b", "p").blocks[0].citations).toEqual([]);
  });
  it("shows uncited blocks as unlinked rather than borrowing a session's claims", () => {
    expect(articleEvidenceRows(content)[0].source_id).toBeNull();
    const next = attachPassage(content, "b", passage, "paper.pdf");
    expect(articleEvidenceRows(next)[0]).toMatchObject({
      source_id: "s", claim_text: "My conclusion", quote: null, strength: "reference",
    });
  });
});
