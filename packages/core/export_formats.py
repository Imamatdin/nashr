"""The one mapping between session export formats and render-wire file formats.

A session, a generation job's payload and the bot all speak :class:`ExportFormat`
(``html``, ``pptx_editable``, ``pptx_studio``, ``pdf``): what the user asked for.
Render jobs, ``revision_exports`` and the API's downloads speak the file format a
render produces (``html``, ``pptx``, ``pdf``). Both PPTX modes render a ``.pptx``
file. Every conversion between the two goes through this module, so the two name
sets cannot drift apart again (B1-FIX3, Codex A3: a session stored the wire name
``pptx`` and every read of it failed).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Final, cast

from packages.core.enums import ExportFormat

WIRE_NAME: Final[Mapping[ExportFormat, str]] = MappingProxyType(
    {
        ExportFormat.HTML: "html",
        ExportFormat.PPTX_EDITABLE: "pptx",
        ExportFormat.PPTX_STUDIO: "pptx",
        ExportFormat.PDF: "pdf",
    }
)

# The renderer mode a stored file format is re-rendered in. A ``.pptx`` export is
# re-rendered as the editable mode, the one every web and bot request asks for.
_FROM_WIRE: Final[Mapping[str, ExportFormat]] = MappingProxyType(
    {
        "html": ExportFormat.HTML,
        "pptx": ExportFormat.PPTX_EDITABLE,
        "pdf": ExportFormat.PDF,
    }
)

WIRE_NAMES: Final[frozenset[str]] = frozenset(_FROM_WIRE)

# Every primary format (SPEC §0 rule 7): what the web delivers.
PRIMARY_FORMATS: Final[tuple[ExportFormat, ...]] = (
    ExportFormat.HTML,
    ExportFormat.PPTX_EDITABLE,
    ExportFormat.PDF,
)


class InvalidExportFormatsError(ValueError):
    """A stored or submitted format list is not a non-empty list of known formats."""


def wire_name(fmt: ExportFormat) -> str:
    """The file format ``fmt`` renders to."""

    return WIRE_NAME[fmt]


def wire_formats(formats: Iterable[ExportFormat]) -> list[str]:
    """The sorted, de-duplicated file formats a render of ``formats`` produces."""

    return sorted({WIRE_NAME[fmt] for fmt in formats})


def from_wire(name: str) -> ExportFormat:
    """The renderer mode for a stored file format; raises on an unknown name."""

    try:
        return _FROM_WIRE[name]
    except KeyError:
        raise InvalidExportFormatsError(f"unknown file format {name!r}") from None


def from_wire_formats(names: Iterable[str]) -> list[ExportFormat]:
    """Renderer modes for stored file formats, one per distinct name, sorted."""

    return [from_wire(name) for name in sorted(set(names))]


def parse_export_formats(raw: object) -> list[ExportFormat]:
    """Strictly parse a persisted or submitted session format list.

    It must be a non-empty JSON array of :class:`ExportFormat` values. A wire name
    (``pptx``) is refused rather than guessed: the value was written by something
    that does not use this mapping, and that is the defect to surface.
    """

    if not isinstance(raw, list) or not raw:
        raise InvalidExportFormatsError("export formats must be a non-empty list")
    parsed: list[ExportFormat] = []
    for item in cast(list[Any], raw):
        if not isinstance(item, str):
            raise InvalidExportFormatsError(f"export format {item!r} is not a string")
        try:
            parsed.append(ExportFormat(item))
        except ValueError:
            raise InvalidExportFormatsError(f"unknown export format {item!r}") from None
    return parsed


__all__ = [
    "PRIMARY_FORMATS",
    "WIRE_NAME",
    "WIRE_NAMES",
    "InvalidExportFormatsError",
    "from_wire",
    "from_wire_formats",
    "parse_export_formats",
    "wire_formats",
    "wire_name",
]
