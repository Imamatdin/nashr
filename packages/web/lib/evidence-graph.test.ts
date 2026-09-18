import { describe, expect, it } from "vitest";
import { buildEvidenceGraph } from "./evidence-graph";

describe("evidence graph", () => {
  it("links only recorded source references, never similar wording", () => {
    const graph = buildEvidenceGraph([
      { claim_text: "Education improves outcomes", source_filename: "paper.pdf", source_id: "a", quote: "outcomes", strength: "strong", chunk_index: 0 },
      { claim_text: "Education improves outcomes", source_filename: null, quote: null, strength: "weak", chunk_index: null },
    ]);
    expect(graph.edges).toEqual([{ source: "source:a", target: "claim:0" }]);
    expect(graph.nodes.find((node) => node.id === "claim:1")?.linked).toBe(false);
  });
  it("keeps different files with identical names separate", () => {
    const rows = ["a", "b"].map((id) => ({ claim_text: id, source_id: id, source_filename: "paper.pdf", quote: null, strength: "weak", chunk_index: 0 }));
    expect(buildEvidenceGraph(rows).nodes.filter((node) => node.kind === "source")).toHaveLength(2);
  });
});
