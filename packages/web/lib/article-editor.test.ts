import { describe, expect, it } from "vitest";
import { addBlock, moveBlock, removeBlock, wordCount } from "./article-editor";
import type { ArticleContent } from "./api";

const content: ArticleContent = {
  kind: "article",
  schema_version: 1,
  title: "Test",
  blocks: [
    { id: "a", type: "heading", level: 2, text: "First", citations: [] },
    {
      id: "b",
      type: "paragraph",
      level: null,
      text: "Two words",
      citations: [],
    },
  ],
};

describe("article editor operations", () => {
  it("adds stable blocks after the selected block", () => {
    const next = addBlock(content, "a", "paragraph", "new");
    expect(next.blocks.map((block) => block.id)).toEqual(["a", "new", "b"]);
  });
  it("never deletes the last block", () => {
    const one = { ...content, blocks: [content.blocks[0]] };
    expect(removeBlock(one, "a")).toBe(one);
  });
  it("moves blocks without changing their identities", () => {
    expect(moveBlock(content, "b", -1).blocks.map((block) => block.id)).toEqual(
      ["b", "a"],
    );
  });
  it("counts words across scripts separated by whitespace", () => {
    expect(
      wordCount({
        ...content,
        blocks: [{ ...content.blocks[1], text: "hello dunyo мир" }],
      }),
    ).toBe(3);
  });
});
