"""Article worker: evidence matrix, interview, drafting, citation verification, DOCX export."""

from packages.workers.article.bibliography import (
    BibliographyFormatter,
    source_to_citation_metadata,
)
from packages.workers.article.citation_verifier import CitationVerifier
from packages.workers.article.claim_linker import ClaimLinker
from packages.workers.article.drafter import ArticleDrafter, SectionDrafter
from packages.workers.article.evidence_matrix import EvidenceMatrixBuilder
from packages.workers.article.interview import ResearchInterviewEngine
from packages.workers.article.outline_generator import OutlineGenerator
from packages.workers.article.pdf_export import ArticlePDFPipeline, PDFExporter

__all__ = [
    "ArticleDrafter",
    "ArticlePDFPipeline",
    "BibliographyFormatter",
    "CitationVerifier",
    "ClaimLinker",
    "EvidenceMatrixBuilder",
    "OutlineGenerator",
    "PDFExporter",
    "ResearchInterviewEngine",
    "SectionDrafter",
    "source_to_citation_metadata",
]
