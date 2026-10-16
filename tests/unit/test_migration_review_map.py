"""ADR 0001's concern-level map of migration 016 is complete and current (B1-FIX4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_review_map", ROOT / "scripts" / "migration_review_map.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_line_of_016_belongs_to_exactly_one_statement_and_concern() -> None:
    generator = _generator()
    lines = generator.MIGRATION.read_text(encoding="utf-8").splitlines()

    statements = generator.statements(lines)

    covered = [n for s in statements for n in range(s.first, s.last + 1)]
    assert covered == list(range(1, len(lines) + 1))
    assert {s.concern for s in statements} == set(generator.CONCERNS)


def test_the_identity_and_session_objects_are_reviewed_together() -> None:
    generator = _generator()
    lines = generator.MIGRATION.read_text(encoding="utf-8").splitlines()
    concern = {s.name: s.concern for s in generator.statements(lines)}

    for name in (
        "_edit_session",
        "generation_jobs_require_edit_identity",
        "brain_sessions_require_cas",
    ):
        assert concern[name] == generator.SESSIONS, name
    assert concern["finish_generation_job"] == generator.LIFECYCLE
    assert concern["policy edit_deliveries_owner_select"] == generator.PRIVILEGES


def test_the_adr_carries_the_map_the_generator_produces() -> None:
    generator = _generator()
    lines = generator.MIGRATION.read_text(encoding="utf-8").splitlines()
    adr = generator.ADR.read_text(encoding="utf-8")

    assert generator.render(lines) in adr, "run python scripts/migration_review_map.py"
