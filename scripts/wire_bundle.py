"""Assemble a phase bundle for the architect read (Session W).

    python scripts/wire_bundle.py p1 <base-ref>

Concatenates every file the phase touched, full text, with a header naming the
commit range — the same shape as review/p2_bundle.txt and review/p3_bundle.txt.
Reads the file list from git so the bundle cannot drift from the diff.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Untracked helper scripts and generated evidence never belong in a review
# bundle: the architect reads the code that ships, not the tooling that
# photographed it.
_SKIP_PREFIXES = ("review/", "scripts/_", "scripts/raw/", "scripts/webshots/_")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _changed_files(base: str, head: str) -> list[str]:
    out = _git("diff", "--name-only", f"{base}..{head}")
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return [f for f in files if not f.startswith(_SKIP_PREFIXES)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Session W phase bundle")
    parser.add_argument("phase", help="phase slug, e.g. p1")
    parser.add_argument("base", help="base ref the phase branched from")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    files = _changed_files(args.base, args.head)
    if not files:
        print(f"no files changed between {args.base} and {args.head}", file=sys.stderr)
        return 1

    out_path = ROOT / "review" / f"wire_{args.phase}_bundle.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    parts: list[str] = [
        f"Session W — phase {args.phase.upper()} bundle",
        f"range: {args.base}..{_git('rev-parse', '--short', args.head).strip()}",
        f"files: {len(files)}",
        "",
        "FILE LIST",
        *(f"  {name}" for name in files),
        "",
    ]
    for name in files:
        path = ROOT / name
        parts.append(f"=== {name} ===")
        if not path.exists():
            parts.append("(deleted in this range)")
        else:
            parts.append(path.read_text(encoding="utf-8", errors="replace").rstrip())
        parts.append("")

    out_path.write_text("\n".join(parts), encoding="utf-8", newline="\n")
    print(f"wrote {out_path.relative_to(ROOT)} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
