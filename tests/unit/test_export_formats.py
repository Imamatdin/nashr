"""The one mapping between session export formats and render-wire file formats (B1-FIX3 A3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from packages.core.enums import ExportFormat
from packages.core.export_formats import (
    PRIMARY_FORMATS,
    WIRE_NAMES,
    InvalidExportFormatsError,
    from_wire,
    from_wire_formats,
    parse_export_formats,
    wire_formats,
    wire_name,
)
from packages.platform.document_models import (
    EXPORT_FILE_FORMATS,
    DocumentKind,
    ExportFileFormat,
)

# Migration 017 seeds the SQL export_file_formats lookup; this file parses that
# seed to prove it matches the Python table. The authoritative drift guard runs
# against real PostgreSQL in tests/db (the seed and Python can still disagree with
# the live table if a later migration edits it, which only Postgres catches).
_MIGRATION_017 = Path(__file__).resolve().parents[2] / "supabase/migrations/017_export_formats.sql"


def test_every_session_format_has_exactly_one_wire_name() -> None:
    assert {fmt: wire_name(fmt) for fmt in ExportFormat} == {
        ExportFormat.HTML: "html",
        ExportFormat.PPTX_EDITABLE: "pptx",
        ExportFormat.PPTX_STUDIO: "pptx",
        ExportFormat.PDF: "pdf",
    }


def test_wire_names_are_presentation_file_formats() -> None:
    # Every session render produces a presentation file format. The stored file
    # formats are a superset (png and docx have no session format; docx is an
    # article format), so the relationship is subset, not equality.
    wire = set(WIRE_NAMES)
    assert wire <= {f.value for f in ExportFileFormat}
    for name in wire:
        spec = EXPORT_FILE_FORMATS[ExportFileFormat(name)]
        assert DocumentKind.PRESENTATION in spec.allowed_kinds


def test_python_format_table_matches_the_sql_seed() -> None:
    sql = _MIGRATION_017.read_text(encoding="utf-8")
    rows = re.findall(
        r"\('([a-z]+)',\s*'([a-z0-9]+)',\s*'([^']+)',\s*array\[([^\]]*)\]\)",
        sql,
    )
    seeded = {
        fmt: (
            ext,
            media,
            frozenset(DocumentKind(k) for k in re.findall(r"'([a-z]+)'", kinds)),
        )
        for fmt, ext, media, kinds in rows
    }
    expected = {
        fmt.value: (spec.file_extension, spec.media_type, spec.allowed_kinds)
        for fmt, spec in EXPORT_FILE_FORMATS.items()
    }
    assert seeded == expected


def test_wire_round_trip_is_stable() -> None:
    assert wire_formats(PRIMARY_FORMATS) == ["html", "pdf", "pptx"]
    assert wire_formats(from_wire_formats(["pptx", "html", "pptx"])) == ["html", "pptx"]
    for name in WIRE_NAMES:
        assert wire_name(from_wire(name)) == name


def test_both_pptx_modes_render_one_pptx_file() -> None:
    assert wire_formats([ExportFormat.PPTX_EDITABLE, ExportFormat.PPTX_STUDIO]) == ["pptx"]


@pytest.mark.parametrize(
    "raw",
    [["html", "pptx"], [], None, "html", ["html", 7], [{"format": "html"}], ["docx"]],
    ids=["wire_name", "empty", "null", "string", "number", "object", "unknown"],
)
def test_a_session_format_list_is_parsed_strictly(raw: object) -> None:
    with pytest.raises(InvalidExportFormatsError):
        parse_export_formats(raw)


def test_a_valid_session_format_list_parses_in_order() -> None:
    assert parse_export_formats(["pdf", "pptx_editable", "html"]) == [
        ExportFormat.PDF,
        ExportFormat.PPTX_EDITABLE,
        ExportFormat.HTML,
    ]


def test_an_unknown_wire_name_is_refused() -> None:
    with pytest.raises(InvalidExportFormatsError):
        from_wire("pptx_editable")
