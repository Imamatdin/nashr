import type { ProvenanceRow } from "./api";

export interface EvidenceNode {
  id: string; label: string; kind: "source" | "claim"; linked: boolean; row?: ProvenanceRow;
}
export interface EvidenceGraph {
  nodes: EvidenceNode[]; edges: { source: string; target: string }[];
}

/** A reference graph, not a model-inferred assertion of causal support. */
export function buildEvidenceGraph(rows: ProvenanceRow[]): EvidenceGraph {
  const sources = new Map<string, EvidenceNode>();
  const claims: EvidenceNode[] = [];
  const edges: EvidenceGraph["edges"] = [];
  rows.forEach((row, index) => {
    const sourceKey = row.source_id || row.source_filename;
    const claimId = `claim:${index}`;
    claims.push({ id: claimId, label: row.claim_text, kind: "claim", linked: Boolean(sourceKey), row });
    if (sourceKey) {
      const sourceId = `source:${sourceKey}`;
      sources.set(sourceId, { id: sourceId, label: row.source_filename || sourceKey, kind: "source", linked: true });
      edges.push({ source: sourceId, target: claimId });
    }
  });
  return { nodes: [...sources.values(), ...claims], edges };
}
