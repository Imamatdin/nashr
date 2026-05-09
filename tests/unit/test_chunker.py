"""Behaviour tests for :class:`SourceChunker`.

The chunker is pure synchronous Python, so these tests construct
:class:`ParsedSource` fixtures directly and assert on the chunk stream's
shape. We deliberately use fixtures whose lengths and punctuation are
chosen to exercise every branch in the splitting algorithm — sentence
boundary, word boundary, hard cut, and trailing-tail merge.

We do not test against real parsed PDFs/DOCX here because chunking
operates on already-extracted text strings; the parser tests cover the
file-format side. Page numbers in this codebase are 1-indexed (see
``ParsedPage.page_number``), so chunks emitted by the chunker carry
``page=1, 2, 3, ...`` rather than 0-indexed values.
"""

from __future__ import annotations

from packages.core.models.source import (
    ParsedPage,
    ParsedSource,
    SourceMetadataExtracted,
)
from packages.workers.source.chunker import SourceChunker


def _page(
    text: str, page_number: int = 1, *, is_ocr: bool = False, ocr_confidence: float | None = None
) -> ParsedPage:
    return ParsedPage(
        page_number=page_number,
        text=text,
        char_count=len(text.replace(" ", "").replace("\n", "")),
        needs_ocr=False,
        is_ocr=is_ocr,
        ocr_confidence=ocr_confidence,
    )


def _source(pages: list[ParsedPage]) -> ParsedSource:
    full = "\n\n".join(p.text for p in pages)
    return ParsedSource(
        filename="fixture.txt",
        file_type="txt",
        file_size_bytes=len(full.encode("utf-8")),
        pages=pages,
        metadata=SourceMetadataExtracted(),
        full_text=full,
        needs_ocr_pages=[],
        parse_errors=[],
    )


def _make_sentence_text(target_chars: int) -> str:
    """Build text with sentence boundaries every ~120 chars, no trailing space."""
    sentence = (
        "Bu erda biz uchinchi avlod ma'lumotlarini ko'rib chiqamiz va ularning "
        "amaliy ahamiyatini batafsil izohlaymiz."
    )
    s = sentence + " "
    pieces: list[str] = []
    while sum(len(p) for p in pieces) < target_chars:
        pieces.append(s)
    text = "".join(pieces).rstrip()
    if not text.endswith("."):
        text += "."
    return text


def test_chunk_short_page_single_chunk() -> None:
    page_text = "Short paragraph with one sentence." * 5  # ~175 chars
    parsed = _source([_page(page_text, page_number=3)])

    chunks = SourceChunker().chunk_parsed_source(parsed)

    assert len(chunks) == 1
    assert chunks[0].text == page_text
    assert chunks[0].page == 3
    assert chunks[0].chunk_index == 0


def test_chunk_long_page_splits_at_sentence_boundary() -> None:
    text = _make_sentence_text(5000)
    parsed = _source([_page(text)])

    chunker = SourceChunker()
    chunks = chunker.chunk_parsed_source(parsed)

    assert len(chunks) >= 2
    tolerance = 200
    for chunk in chunks:
        assert len(chunk.text) <= chunker.CHUNK_SIZE + tolerance
    for chunk in chunks[:-1]:
        last_char = chunk.text.rstrip()[-1]
        assert last_char in {".", "!", "?"}, (
            f"Non-final chunk should end at sentence boundary, got '{last_char}'"
        )


def test_chunk_overlap_preserved() -> None:
    text = _make_sentence_text(5000)
    parsed = _source([_page(text)])

    chunker = SourceChunker()
    chunks = chunker.chunk_parsed_source(parsed)

    assert len(chunks) >= 2
    tail = chunks[0].text[-chunker.CHUNK_OVERLAP :]
    head = chunks[1].text[: chunker.CHUNK_OVERLAP]
    assert tail == head, "Tail of chunk[0] must equal head of chunk[1] (CHUNK_OVERLAP chars)"


def test_chunk_preserves_page_boundaries() -> None:
    page_text = "Sentence with content. " * 60  # ~1380 chars per page
    parsed = _source(
        [
            _page(page_text, page_number=1),
            _page(page_text, page_number=2),
            _page(page_text, page_number=3),
        ]
    )

    chunks = SourceChunker().chunk_parsed_source(parsed)

    assert len(chunks) == 3
    assert chunks[0].page == 1
    assert chunks[1].page == 2
    assert chunks[2].page == 3


def test_chunk_skips_empty_pages() -> None:
    parsed = _source(
        [
            _page("First page content goes here.", page_number=1),
            _page("", page_number=2),
            _page("Third page content here too.", page_number=3),
        ]
    )

    chunks = SourceChunker().chunk_parsed_source(parsed)

    assert len(chunks) == 2
    assert chunks[0].page == 1
    assert chunks[1].page == 3


def test_chunk_tiny_trailing_text_merged() -> None:
    """Text whose natural split would leave a sub-MIN tail must merge it.

    With CHUNK_SIZE=2000 and MIN_CHUNK_SIZE=100, a 2050-char block with no
    sentence/word boundaries would otherwise emit a 50-char tail. The
    chunker absorbs that tail into the preceding chunk so no chunk smaller
    than ``MIN_CHUNK_SIZE`` is ever produced.
    """

    chunker = SourceChunker()
    text = "a" * (chunker.CHUNK_SIZE + 50)
    parsed = _source([_page(text)])

    chunks = chunker.chunk_parsed_source(parsed)

    for chunk in chunks:
        assert len(chunk.text) >= chunker.MIN_CHUNK_SIZE
    assert "".join(c.text for c in chunks).count("a") >= len(text)


def test_chunk_no_word_boundary_hard_cuts() -> None:
    chunker = SourceChunker()
    text = "a" * 5000
    parsed = _source([_page(text)])

    chunks = chunker.chunk_parsed_source(parsed)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.text) <= chunker.CHUNK_SIZE + 50


def test_chunk_indexes_are_sequential() -> None:
    long_text = _make_sentence_text(5000)
    parsed = _source(
        [
            _page(long_text, page_number=1),
            _page("Short page two content.", page_number=2),
            _page(long_text, page_number=3),
        ]
    )

    chunks = SourceChunker().chunk_parsed_source(parsed)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_preserves_ocr_flag() -> None:
    parsed = _source(
        [
            _page(
                "Some recognised text from a scan.", page_number=1, is_ocr=True, ocr_confidence=85.5
            ),
        ]
    )

    chunks = SourceChunker().chunk_parsed_source(parsed)

    assert len(chunks) == 1
    assert chunks[0].is_ocr is True


def test_chunk_preserves_ocr_confidence() -> None:
    parsed = _source(
        [
            _page(
                "Recognised but low-confidence sample.",
                page_number=1,
                is_ocr=True,
                ocr_confidence=85.5,
            ),
        ]
    )

    chunks = SourceChunker().chunk_parsed_source(parsed)

    assert len(chunks) == 1
    assert chunks[0].confidence == 85.5
