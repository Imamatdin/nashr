"""PostToolUse hook: auto-run ruff check --fix and ruff format on edited Python files."""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith(".py"):
        return 0

    subprocess.run(["ruff", "check", "--fix", "--quiet", file_path], check=False)
    subprocess.run(["ruff", "format", "--quiet", file_path], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
