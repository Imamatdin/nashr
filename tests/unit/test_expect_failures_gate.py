"""The old-schema gate accepts only intended failures (tests/db/expect_failures.py).

Cases are keyed by full test id (``<classname>::<name>``), so two modules with a
test of the same short name cannot overwrite each other (B1-FIX2 item 9).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.db.expect_failures import verdict

INVENTORY: dict[str, Any] = {
    "schema": "old",
    "tests": {
        "tests.db.m::test_bug": {
            "expect": "fail",
            "match": r"DID NOT RAISE .*UniqueViolationError",
        },
        "tests.db.m::test_coverage": {"expect": "pass"},
    },
}


def _report(tmp_path: Path, cases: str) -> Path:
    path = tmp_path / "report.xml"
    path.write_text(f'<testsuites><testsuite name="db">{cases}</testsuite></testsuites>')
    return path


INTENDED = (
    '<testcase classname="tests.db.m" name="test_bug"><failure message="Failed: DID NOT RAISE'
    " &lt;class 'asyncpg.exceptions.UniqueViolationError'&gt;\"/></testcase>"
)
COVERAGE = '<testcase classname="tests.db.m" name="test_coverage"/>'


def test_intended_failures_and_passing_coverage_are_green(tmp_path: Path) -> None:
    assert verdict(_report(tmp_path, INTENDED + COVERAGE), INVENTORY) == []


def test_a_setup_error_is_not_evidence_of_the_bug(tmp_path: Path) -> None:
    errored = '<testcase classname="tests.db.m" name="test_bug"><error message="UndefinedTableError: x"/></testcase>'
    problems = verdict(_report(tmp_path, errored + COVERAGE), INVENTORY)
    assert problems == ["tests.db.m::test_bug: expected an assertion failure, got error"]


def test_a_failure_for_another_reason_is_rejected(tmp_path: Path) -> None:
    other = '<testcase classname="tests.db.m" name="test_bug"><failure message="AssertionError: assert 1 == 2"/></testcase>'
    problems = verdict(_report(tmp_path, other + COVERAGE), INVENTORY)
    assert len(problems) == 1 and problems[0].startswith(
        "tests.db.m::test_bug: failed, but not with"
    )


def test_a_passing_regression_test_is_rejected(tmp_path: Path) -> None:
    passed = '<testcase classname="tests.db.m" name="test_bug"/>'
    problems = verdict(_report(tmp_path, passed + COVERAGE), INVENTORY)
    assert problems == ["tests.db.m::test_bug: expected an assertion failure, got passed"]


def test_missing_and_unlisted_tests_are_rejected(tmp_path: Path) -> None:
    extra = '<testcase classname="tests.db.m" name="test_new"/>'
    problems = verdict(_report(tmp_path, INTENDED + extra), INVENTORY)
    assert problems == [
        "tests.db.m::test_new: ran but is not in the inventory",
        "tests.db.m::test_coverage: in the inventory but did not run",
    ]


def test_skipped_coverage_is_rejected(tmp_path: Path) -> None:
    skipped = '<testcase classname="tests.db.m" name="test_coverage"><skipped message="no db"/></testcase>'
    problems = verdict(_report(tmp_path, INTENDED + skipped), INVENTORY)
    assert problems == ["tests.db.m::test_coverage: expected to pass on the old schema, skipped"]


def test_the_same_short_name_in_two_modules_is_two_cases(tmp_path: Path) -> None:
    # Keyed by short name, the second module's pass would overwrite the first
    # module's intended failure and the gate would judge the wrong result.
    other_module = '<testcase classname="tests.db.other" name="test_bug"/>'
    problems = verdict(_report(tmp_path, INTENDED + COVERAGE + other_module), INVENTORY)
    assert problems == ["tests.db.other::test_bug: ran but is not in the inventory"]


def test_a_duplicated_full_id_is_refused(tmp_path: Path) -> None:
    problems = verdict(_report(tmp_path, INTENDED + INTENDED + COVERAGE), INVENTORY)
    assert problems == ["tests.db.m::test_bug: appears more than once in the report"]
