"""The old-schema gate accepts only intended failures (tests/db/expect_failures.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.db.expect_failures import verdict

INVENTORY: dict[str, Any] = {
    "schema": "old",
    "tests": {
        "test_bug": {"expect": "fail", "match": r"DID NOT RAISE .*UniqueViolationError"},
        "test_coverage": {"expect": "pass"},
    },
}


def _report(tmp_path: Path, cases: str) -> Path:
    path = tmp_path / "report.xml"
    path.write_text(f'<testsuites><testsuite name="db">{cases}</testsuite></testsuites>')
    return path


INTENDED = (
    '<testcase name="test_bug"><failure message="Failed: DID NOT RAISE'
    " &lt;class 'asyncpg.exceptions.UniqueViolationError'&gt;\"/></testcase>"
)
COVERAGE = '<testcase name="test_coverage"/>'


def test_intended_failures_and_passing_coverage_are_green(tmp_path: Path) -> None:
    assert verdict(_report(tmp_path, INTENDED + COVERAGE), INVENTORY) == []


def test_a_setup_error_is_not_evidence_of_the_bug(tmp_path: Path) -> None:
    errored = '<testcase name="test_bug"><error message="UndefinedTableError: x"/></testcase>'
    problems = verdict(_report(tmp_path, errored + COVERAGE), INVENTORY)
    assert problems == ["test_bug: expected an assertion failure, got error"]


def test_a_failure_for_another_reason_is_rejected(tmp_path: Path) -> None:
    other = (
        '<testcase name="test_bug"><failure message="AssertionError: assert 1 == 2"/></testcase>'
    )
    problems = verdict(_report(tmp_path, other + COVERAGE), INVENTORY)
    assert len(problems) == 1 and problems[0].startswith("test_bug: failed, but not with")


def test_a_passing_regression_test_is_rejected(tmp_path: Path) -> None:
    passed = '<testcase name="test_bug"/>'
    problems = verdict(_report(tmp_path, passed + COVERAGE), INVENTORY)
    assert problems == ["test_bug: expected an assertion failure, got passed"]


def test_missing_and_unlisted_tests_are_rejected(tmp_path: Path) -> None:
    extra = '<testcase name="test_new"/>'
    problems = verdict(_report(tmp_path, INTENDED + extra), INVENTORY)
    assert problems == [
        "test_new: ran but is not in the inventory",
        "test_coverage: in the inventory but did not run",
    ]


def test_skipped_coverage_is_rejected(tmp_path: Path) -> None:
    skipped = '<testcase name="test_coverage"><skipped message="no db"/></testcase>'
    problems = verdict(_report(tmp_path, INTENDED + skipped), INVENTORY)
    assert problems == ["test_coverage: expected to pass on the old schema, skipped"]
