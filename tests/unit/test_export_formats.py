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
from packages.platform.document_models import ExportFileFormat

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "supabase/migrations/016_canonical_document_state.sql"
)


def test_every_session_format_has_exactly_one_wire_name() -> None:
    assert {fmt: wire_name(fmt) for fmt in ExportFormat} == {
        ExportFormat.HTML: "html",
        ExportFormat.PPTX_EDITABLE: "pptx",
        ExportFormat.PPTX_STUDIO: "pptx",
        ExportFormat.PDF: "pdf",
    }


def test_wire_names_are_the_export_rows_and_the_sql_checks() -> None:
    assert {f.value for f in ExportFileFormat} == set(WIRE_NAMES)
    sql = _MIGRATION.read_text(encoding="utf-8")
    checks = re.findall(r"format\s+text not null check \(format in \(([^)]*)\)\)", sql)
    assert [set(re.findall(r"'([a-z]+)'", c)) for c in checks] == [set(WIRE_NAMES)]
    render_checks = re.findall(r"f not in \(([^)]*)\)", sql)
    assert render_checks and all(
        set(re.findall(r"'([a-z]+)'", c)) == set(WIRE_NAMES) for c in render_checks
    )


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
