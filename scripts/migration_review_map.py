"""Generate the concern-level review map of migration 016 into ADR 0001 (B1-FIX4).

Migration 016 stays one executable file, applied in one transaction (splitting it
would change how a failed deployment rolls back; Codex review of 3723d30). To keep
it reviewable by concern, this script splits it into its top-level statements,
assigns each one to one of six concerns, and writes a table of every concern's
objects with their line ranges into the ADR between two markers.

    python scripts/migration_review_map.py           # rewrite the ADR's map
    python scripts/migration_review_map.py --check   # exit 1 if the map is stale

Every line of the file belongs to exactly one statement and every statement to
exactly one concern; tests/unit/test_migration_review_map.py holds both and that
the ADR's map is the one this script generates.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
MIGRATION: Final[Path] = ROOT / "supabase" / "migrations" / "016_canonical_document_state.sql"
ADR: Final[Path] = ROOT / "docs" / "adr" / "0001-canonical-document-state.md"
START: Final[str] = "<!-- migration-016-review-map:start (scripts/migration_review_map.py) -->"
END: Final[str] = "<!-- migration-016-review-map:end -->"

SCHEMA = "Schema and constraints"
REVISIONS = "Canonical revision functions"
LIFECYCLE = "Job, export and delivery lifecycle"
SESSIONS = "Session compare-and-swap and edit identity"
PRIVILEGES = "Grants, row security and hardening"
BACKFILL = "Backfill, view swap and validation"
CONCERNS: Final[tuple[str, ...]] = (SCHEMA, REVISIONS, LIFECYCLE, SESSIONS, PRIVILEGES, BACKFILL)

# The concern of each numbered section; the overrides below move single objects.
_SECTION_CONCERN: Final[dict[str, str]] = {
    "0": BACKFILL,  # the header and the PostgreSQL version guard
    "1": SCHEMA,
    "2": SCHEMA,
    "3": SCHEMA,
    "4": PRIVILEGES,
    "5": REVISIONS,
    "6": REVISIONS,
    "7": REVISIONS,
    "7b": LIFECYCLE,
    "7c": LIFECYCLE,
    "8": REVISIONS,
    "9": LIFECYCLE,
    "10": PRIVILEGES,
    "10b": PRIVILEGES,
    "11": LIFECYCLE,
    "12": LIFECYCLE,
    "13": BACKFILL,
}
_OBJECT_CONCERN: Final[dict[str, str]] = {
    "brain_sessions": SESSIONS,
    "brain_sessions_require_cas": SESSIONS,
    "trigger brain_sessions_require_cas": SESSIONS,
    "edit_deliveries": LIFECYCLE,
    "idx_edit_deliveries_session": LIFECYCLE,
    "idx_edit_deliveries_project": LIFECYCLE,
    "_edit_session": SESSIONS,
    "generation_jobs_require_edit_identity": SESSIONS,
    "trigger generation_jobs_require_edit_identity": SESSIONS,
    "acknowledge_edit_notices": SESSIONS,
    "migration_reports": BACKFILL,
    "proposal_validations": REVISIONS,
    "revision_validations": REVISIONS,
    "record_proposal_validation": REVISIONS,
    "record_revision_validation": REVISIONS,
}

_SECTION = re.compile(r"^-- (\d+[a-z]?)\. ")
_DEFINITION = re.compile(
    r"^(?:create (?:or replace )?function (?P<function>[a-z_0-9]+)"
    r"|create table (?:if not exists )?(?P<table>[a-z_0-9]+)"
    r"|alter table (?:if exists )?(?P<altered>[a-z_0-9]+)"
    r"|create (?:unique )?index (?:if not exists )?(?P<index>[a-z_0-9]+)"
    r"|create trigger (?P<trigger>[a-z_0-9]+)"
    r"|create policy (?P<policy>[a-z_0-9]+)"
    r"|create (?:or replace )?view (?P<view>[a-z_0-9]+)"
    r"|do \$\$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Statement:
    """A run of migration lines that starts at one definition (1-based, inclusive)."""

    name: str
    section: str
    first: int
    last: int

    @property
    def concern(self) -> str:
        # Row security and grants on any object stay with the privileges.
        if _SECTION_CONCERN[self.section] == PRIVILEGES:
            return PRIVILEGES
        return _OBJECT_CONCERN.get(self.name) or _SECTION_CONCERN[self.section]


def _name(match: re.Match[str], line_no: int) -> str:
    groups = match.groupdict()
    for kind in ("function", "table", "altered", "index", "view"):
        if groups[kind]:
            return groups[kind].lower()
    if groups["trigger"]:
        return f"trigger {groups['trigger'].lower()}"
    if groups["policy"]:
        return f"policy {groups['policy'].lower()}"
    return f"do block @{line_no}"


def statements(lines: list[str]) -> list[Statement]:
    """Split the migration into statements; consecutive same-name ones are merged.

    Every top-level definition in 016 starts in column 0 and every function body
    line is indented, so a definition is a column-0 match. A section's banner (the
    dashed rule above its "-- N." heading) starts that section's notes.
    """

    starts: list[tuple[int, str, str]] = [(1, "(header)", "0")]
    section = "0"
    for number, line in enumerate(lines, start=1):
        header = _SECTION.match(line)
        if header:
            section = header.group(1)
            banner = number - 1 if number > 1 and lines[number - 2].startswith("-- ---") else number
            starts.append((banner, f"section {section} notes", section))
            continue
        definition = _DEFINITION.match(line)
        if definition:
            starts.append((number, _name(definition, number), section))
    result: list[Statement] = []
    for index, (first, name, sect) in enumerate(starts):
        last = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
        if result and result[-1].name == name and result[-1].section == sect:
            result[-1] = Statement(name, sect, result[-1].first, last)
        else:
            result.append(Statement(name, sect, first, last))
    return result


def render(lines: list[str]) -> str:
    """The ADR's map: per concern, its line total and its objects with their lines."""

    found = statements(lines)
    out = [
        START,
        "",
        f"Generated from `{MIGRATION.relative_to(ROOT).as_posix()}` ({len(lines)} lines);"
        " regenerate with `python scripts/migration_review_map.py`. Each object's lines run"
        " from its definition to the next one, so its comments and grants travel with it.",
        "",
        "| Concern | Lines | Objects (first–last line) |",
        "|---|---|---|",
    ]
    for concern in CONCERNS:
        mine = [s for s in found if s.concern == concern]
        total = sum(s.last - s.first + 1 for s in mine)
        objects = ", ".join(f"`{s.name}` {s.first}–{s.last}" for s in mine)
        out.append(f"| {concern} | {total} | {objects} |")
    out += ["", END]
    return "\n".join(out)


def _adr_with_map(adr: str, block: str) -> str:
    if START not in adr or END not in adr:
        raise SystemExit(f"{ADR.name} has no review-map markers")
    before, rest = adr.split(START, 1)
    _old, after = rest.split(END, 1)
    return before + block + after


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the ADR's map is stale")
    args = parser.parse_args()
    lines = MIGRATION.read_text(encoding="utf-8").splitlines()
    adr = ADR.read_text(encoding="utf-8")
    updated = _adr_with_map(adr, render(lines))
    if args.check:
        if updated != adr:
            print(
                "the ADR's migration 016 review map is stale; run scripts/migration_review_map.py"
            )
            return 1
        return 0
    ADR.write_bytes(updated.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
