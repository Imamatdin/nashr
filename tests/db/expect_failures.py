"""CI helper: prove every bug-regression test FAILED on the pre-change schema.

    python -m tests.db.expect_failures artifacts/prechange.xml

Reads the pytest JUnit report of the legacy run (migrations 001–015). Exits 0
only when each ``test_<letter>_*`` bug test failed or errored there; one that
passed would mean the test does not actually detect the bug it names.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ElementTree


def main() -> int:
    tree = ElementTree.parse(sys.argv[1])
    outcomes: dict[str, str] = {}
    for case in tree.iter("testcase"):
        name = case.get("name", "")
        if not name.startswith("test_") or name == "test_export_key_shape":
            continue
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        outcomes[name] = "failed" if failed else "skipped" if skipped else "passed"
    for name, outcome in sorted(outcomes.items()):
        print(f"{outcome:>7}  {name}")
    passed = [name for name, outcome in outcomes.items() if outcome != "failed"]
    if not outcomes or passed:
        print(f"expected every bug test to fail before the change; did not fail: {passed}")
        return 1
    print(f"all {len(outcomes)} bug tests fail on the pre-change schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
