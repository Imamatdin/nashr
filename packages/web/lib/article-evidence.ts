import type { ArticleContent, EvidencePassage, ProvenanceRow } from "./api";

export function attachPassage(content: ArticleContent, blockId: string, passage: EvidencePassage, filename: string): ArticleContent {
  const block = content.blocks.find((item) => item.id === blockId);
  if (!block || block.citations.length >= 100 || block.citations.some((citation) => citation.passage_id === passage.id)) return content;
  if (content.blocks.reduce((count, item) => count + item.citations.length, 0) >= 1000) return content;
  const citation = {
    source_id: passage.source_id, passage_id: passage.id, claim_id: null,
    label: passage.page ? `${filename} · ${passage.page}` : filename,
  };
  return { ...content, blocks: content.blocks.map((item) => item.id === blockId ? { ...item, citations: [...item.citations, citation] } : item) };
}

export function detachCitation(content: ArticleContent, blockId: string, targetId: string): ArticleContent {
  return { ...content, blocks: content.blocks.map((block) => block.id === blockId ? {
    ...block, citations: block.citations.filter((citation) => (citation.passage_id ?? citation.claim_id) !== targetId),
  } : block) };
}

/** Only actual article references become graph edges; uncited text stays unlinked. */
export function articleEvidenceRows(content: ArticleContent): ProvenanceRow[] {
  return content.blocks.filter((block) => block.type !== "heading" && block.text.trim()).flatMap<ProvenanceRow>((block) => {
    const common = { claim_text: block.text, quote: null, strength: "reference", chunk_index: null };
    return block.citations.length
      ? block.citations.map((citation) => ({ ...common, source_id: citation.source_id, source_filename: citation.label }))
      : [{ ...common, source_id: null, source_filename: null }];
  });
}
