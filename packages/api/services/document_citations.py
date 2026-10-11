"""Resolve article references against persisted, project-owned evidence."""

from __future__ import annotations

from fastapi import HTTPException

from packages.core.models.document import ArticleDocumentContent
from packages.platform.database import DatabaseClient


async def validate_document_citations(
    db: DatabaseClient, project_id: str, content: ArticleDocumentContent
) -> None:
    """Reject invented IDs and canonicalize labels; do not infer factual support."""

    citations = [citation for block in content.blocks for citation in block.citations]
    if not citations:
        return
    claim_ids = list({str(c.claim_id) for c in citations if c.claim_id})
    claims = await db.get_citation_targets(project_id, claim_ids, claims=True) if claim_ids else []
    claim_chunks = {str(row["id"]): str(row["source_chunk_id"]) for row in claims}
    passage_ids = list(
        {str(c.passage_id) for c in citations if c.passage_id} | set(claim_chunks.values())
    )
    rows = await db.get_citation_targets(project_id, passage_ids) if passage_ids else []
    chunks = {str(row["id"]): row for row in rows}
    sources = {str(row["id"]): row for row in await db.get_project_sources(project_id)}
    for citation in citations:
        passage_id = (
            str(citation.passage_id)
            if citation.passage_id
            else claim_chunks.get(str(citation.claim_id))
        )
        chunk = chunks.get(passage_id or "")
        source = sources.get(str(citation.source_id))
        if source is None or chunk is None or str(chunk["source_id"]) != str(citation.source_id):
            raise HTTPException(status_code=422, detail="citation_target_not_found")
        page = chunk.get("page")
        citation.label = f"{source['filename']} · {page}" if page else str(source["filename"])
