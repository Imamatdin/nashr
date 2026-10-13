"""CI helper: prove the journey's delivery steps fail on the app as of 8cc000b.

    python scripts/webshots/expect_journey.py <results.json> <inventory.json>

The inventory names every step expected in the run and the message each must
fail with. Green only when exactly those steps ran and each failed for its
stated reason (a missing step, an extra step or a pass is red).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, cast


def verdict(results: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    """Every reason the run does not satisfy the inventory (empty = green)."""

    expected = cast(dict[str, dict[str, str]], inventory["steps"])
    ran = {str(r["name"]): r for r in cast(list[dict[str, Any]], results["results"])}
    problems = [
        f"{name}: ran but is not in the inventory" for name in sorted(set(ran) - set(expected))
    ]
    problems += [f"{name}: did not run" for name in sorted(set(expected) - set(ran))]
    for name in sorted(set(expected) & set(ran)):
        outcome = ran[name]
        if outcome.get("ok"):
            problems.append(f"{name}: expected to fail on the old app, passed")
        elif not re.search(expected[name]["match"], str(outcome.get("error", ""))):
            problems.append(
                f"{name}: failed, but not with /{expected[name]['match']}/: {outcome.get('error')!r}"
            )
    return problems


def main() -> int:
    results = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    inventory = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    for outcome in results["results"]:
        print(
            f"{'pass' if outcome.get('ok') else 'fail':>5}  {outcome['name']}: {outcome.get('error', '')}"
        )
    problems = verdict(results, inventory)
    for problem in problems:
        print(f"GATE: {problem}")
    if problems:
        return 1
    print(
        f"{inventory['app']}: all {len(inventory['steps'])} delivery steps failed for their intended reason"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
