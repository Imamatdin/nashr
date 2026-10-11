"""Slide- and block-level revision diffs (the accept-proposal consent view)."""

from __future__ import annotations

from typing import Any

from packages.core.enums import DiffChange, DiffUnit
from packages.core.revision_diff import RevisionDiff, diff_revisions


def _slide(slide_id: str, title: str) -> dict[str, Any]:
    return {"slide_id": slide_id, "slide_type": "content_split", "content": {"title": title}}


def _deck(*slides: dict[str, Any], title: str = "Deck") -> dict[str, Any]:
    return {"title": title, "created_at": "2026-01-01T00:00:00Z", "slides": list(slides)}


def _changes(diff: RevisionDiff) -> list[tuple[str, DiffChange]]:
    return [(entry.item_id, entry.change) for entry in diff.entries]


def test_identical_revisions_have_an_empty_diff() -> None:
    deck = _deck(_slide("a", "One"), _slide("b", "Two"))
    assert diff_revisions(DiffUnit.SLIDE, deck, dict(deck)).is_empty


def test_added_removed_and_changed_slides_are_matched_by_id() -> None:
    before = _deck(_slide("a", "One"), _slide("b", "Two"))
    after = _deck(_slide("a", "One, sharper"), _slide("c", "Three"))

    diff = diff_revisions(DiffUnit.SLIDE, before, after)

    assert _changes(diff) == [
        ("a", DiffChange.CHANGED),
        ("c", DiffChange.ADDED),
        ("b", DiffChange.REMOVED),
    ]
    assert diff.entries[0].label == "One, sharper"
    assert diff.entries[2].label == "Two"


def test_reordering_without_content_change_is_a_move() -> None:
    before = _deck(_slide("a", "One"), _slide("b", "Two"), _slide("c", "Three"))
    after = _deck(_slide("b", "Two"), _slide("a", "One"), _slide("c", "Three"))

    diff = diff_revisions(DiffUnit.SLIDE, before, after)

    assert _changes(diff) == [("b", DiffChange.MOVED), ("a", DiffChange.MOVED)]


def test_an_insert_alone_does_not_mark_later_slides_as_moved() -> None:
    before = _deck(_slide("a", "One"), _slide("b", "Two"))
    after = _deck(_slide("new", "Intro"), _slide("a", "One"), _slide("b", "Two"))

    assert _changes(diff_revisions(DiffUnit.SLIDE, before, after)) == [("new", DiffChange.ADDED)]


def test_top_level_fields_are_reported_but_created_at_is_not() -> None:
    before = _deck(_slide("a", "One"), title="Old")
    after = {**_deck(_slide("a", "One"), title="New"), "created_at": "2026-02-02T00:00:00Z"}

    diff = diff_revisions(DiffUnit.SLIDE, before, after)

    assert diff.entries == []
    assert diff.fields_changed == ["title"]


def test_an_empty_document_diffs_as_all_added() -> None:
    diff = diff_revisions(DiffUnit.SLIDE, None, _deck(_slide("a", "One")))
    assert _changes(diff) == [("a", DiffChange.ADDED)]


def test_article_blocks_diff_by_block_id_with_text_labels() -> None:
    before = {"title": "T", "blocks": [{"id": "x", "type": "paragraph", "text": "first draft"}]}
    after = {"title": "T", "blocks": [{"id": "x", "type": "paragraph", "text": "second draft"}]}

    diff = diff_revisions(DiffUnit.BLOCK, before, after)

    assert _changes(diff) == [("x", DiffChange.CHANGED)]
    assert diff.entries[0].label == "second draft"


def test_legacy_content_without_slides_still_diffs() -> None:
    diff = diff_revisions(DiffUnit.SLIDE, {"legacy_raw": [1]}, _deck(_slide("a", "One")))
    assert _changes(diff) == [("a", DiffChange.ADDED)]
    assert "legacy_raw" in diff.fields_changed
