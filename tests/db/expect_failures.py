"""CI helper: prove each regression test failed on the old schema for its intended reason.

    python -m tests.db.expect_failures artifacts/prechange.xml tests/db/inventory_legacy.json

Reads a pytest JUnit report and an exact inventory. The verdict is green only when
the report contains exactly the inventory's tests, nothing errored or was skipped
(a setup or collection error is not evidence that a bug was detected), every
``fail`` entry failed with a message matching its ``match`` pattern (the SQLSTATE,
exception or assertion the test exists to observe), and every ``pass`` entry
passed (coverage tests that guard a property the old schema already had).
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, cast


def _outcomes(report: Path) -> dict[str, tuple[str, str]]:
    """Each test's outcome (passed/failed/error/skipped) and failure text."""

    found: dict[str, tuple[str, str]] = {}
    for case in ElementTree.parse(report).iter("testcase"):
        name = case.get("name", "")
        failure = case.find("failure")
        error = case.find("error")
        if error is not None:
            found[name] = ("error", f"{error.get('message', '')}\n{error.text or ''}")
        elif failure is not None:
            found[name] = ("failed", f"{failure.get('message', '')}\n{failure.text or ''}")
        elif case.find("skipped") is not None:
            found[name] = ("skipped", "")
        else:
            found[name] = ("passed", "")
    return found


def verdict(report: Path, inventory: dict[str, Any]) -> list[str]:
    """Every reason the report does not satisfy the inventory (empty = green)."""

    expected = cast(dict[str, dict[str, str]], inventory["tests"])
    outcomes = _outcomes(report)
    problems: list[str] = []
    for name in sorted(set(outcomes) - set(expected)):
        problems.append(f"{name}: ran but is not in the inventory")
    for name in sorted(set(expected) - set(outcomes)):
        problems.append(f"{name}: in the inventory but did not run")
    for name in sorted(set(expected) & set(outcomes)):
        outcome, text = outcomes[name]
        want = expected[name]
        if want["expect"] == "pass":
            if outcome != "passed":
                problems.append(f"{name}: expected to pass on the old schema, {outcome}")
            continue
        if outcome != "failed":
            problems.append(f"{name}: expected an assertion failure, got {outcome}")
        elif not re.search(want["match"], text):
            problems.append(f"{name}: failed, but not with /{want['match']}/: {text[:300]!r}")
    return problems


def main() -> int:
    report, inventory_path = Path(sys.argv[1]), Path(sys.argv[2])
    inventory = cast(dict[str, Any], json.loads(inventory_path.read_text(encoding="utf-8")))
    outcomes = _outcomes(report)
    for name, (outcome, _text) in sorted(outcomes.items()):
        print(f"{outcome:>7}  {name}")
    problems = verdict(report, inventory)
    for problem in problems:
        print(f"GATE: {problem}")
    if problems:
        return 1
    failing = sum(1 for want in inventory["tests"].values() if want["expect"] == "fail")
    print(
        f"{inventory['schema']}: all {failing} regression tests failed for their intended reason;"
        f" {len(inventory['tests']) - failing} coverage tests passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
