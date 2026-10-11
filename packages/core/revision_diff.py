"""Slide- and block-level differences between two document revisions (ADR 0001).

Accepting a proposal replaces the head the user is looking at, so the user must
see two diffs first: base → proposal (what the AI changed) and head → proposal
(what accepting will actually change, including the user's own later edits that
it would revert). These are pure functions over raw revision content, because a
legacy revision may not validate against today's models and still needs a diff.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import DiffChange, DiffUnit

_LABEL_CHARS = 120
_IGNORED_FIELDS = frozenset({"created_at"})


class DiffEntry(BaseModel):
    """One slide or block that differs."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item_id: str = Field(min_length=1, max_length=64)
    change: DiffChange
    label: str = Field(max_length=_LABEL_CHARS)
    before_index: int | None = None
    after_index: int | None = None


class RevisionDiff(BaseModel):
    """Every changed slide/block plus the changed top-level fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    unit: DiffUnit
    entries: list[DiffEntry] = Field(default_factory=list[DiffEntry], max_length=5000)
    fields_changed: list[str] = Field(default_factory=list[str], max_length=100)

    @property
    def is_empty(self) -> bool:
        """True when the two revisions do not differ."""

        return not self.entries and not self.fields_changed


def _collection(unit: DiffUnit) -> tuple[str, str]:
    return ("slides", "slide_id") if unit is DiffUnit.SLIDE else ("blocks", "id")


def _items(content: Mapping[str, Any] | None, unit: DiffUnit) -> list[tuple[str, dict[str, Any]]]:
    if content is None:
        return []
    name, key = _collection(unit)
    raw = content.get(name)
    if not isinstance(raw, list):
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for index, entry in enumerate(cast(list[Any], raw)):
        if not isinstance(entry, dict):
            continue
        item = cast(dict[str, Any], entry)
        identity = item.get(key)
        items.append((str(identity) if identity else f"#{index}", item))
    return items


def _label(unit: DiffUnit, item: Mapping[str, Any]) -> str:
    if unit is DiffUnit.SLIDE:
        content = item.get("content")
        title = cast(dict[str, Any], content).get("title") if isinstance(content, dict) else None
        text = title if isinstance(title, str) else item.get("slide_type")
    else:
        text = item.get("text") or item.get("type")
    return " ".join(str(text or "").split())[:_LABEL_CHARS]


def diff_revisions(
    unit: DiffUnit, before: Mapping[str, Any] | None, after: Mapping[str, Any]
) -> RevisionDiff:
    """Compare ``before`` (None for an empty document) with ``after``.

    Each slide/block is matched by its stable id. One present on both sides is
    ``changed`` when its content differs, else ``moved`` when its position among
    the shared items differs. Top-level fields other than the slide/block list are
    reported by name (``created_at`` is a stamp, not a change the user made).
    """

    before_items = _items(before, unit)
    after_items = _items(after, unit)
    before_map = {item_id: (index, item) for index, (item_id, item) in enumerate(before_items)}
    after_map = {item_id: (index, item) for index, (item_id, item) in enumerate(after_items)}
    shared_before = [item_id for item_id, _ in before_items if item_id in after_map]
    shared_after = [item_id for item_id, _ in after_items if item_id in before_map]

    entries: list[DiffEntry] = []
    for after_index, (item_id, item) in enumerate(after_items):
        if item_id not in before_map:
            entries.append(
                DiffEntry(
                    item_id=item_id,
                    change=DiffChange.ADDED,
                    label=_label(unit, item),
                    after_index=after_index,
                )
            )
            continue
        before_index, previous = before_map[item_id]
        if previous != item:
            change = DiffChange.CHANGED
        elif shared_before.index(item_id) != shared_after.index(item_id):
            change = DiffChange.MOVED
        else:
            continue
        entries.append(
            DiffEntry(
                item_id=item_id,
                change=change,
                label=_label(unit, item),
                before_index=before_index,
                after_index=after_index,
            )
        )
    for before_index, (item_id, item) in enumerate(before_items):
        if item_id not in after_map:
            entries.append(
                DiffEntry(
                    item_id=item_id,
                    change=DiffChange.REMOVED,
                    label=_label(unit, item),
                    before_index=before_index,
                )
            )

    name, _ = _collection(unit)
    previous_fields: Mapping[str, Any] = before or {}
    keys = (set(previous_fields) | set(after)) - {name} - _IGNORED_FIELDS
    fields_changed = sorted(key for key in keys if previous_fields.get(key) != after.get(key))
    return RevisionDiff(unit=unit, entries=entries, fields_changed=fields_changed)


__all__ = ["DiffEntry", "RevisionDiff", "diff_revisions"]
