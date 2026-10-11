"""Inspect real Docker SDK build archives without requiring a Docker daemon."""

import tarfile
from pathlib import Path

from docker.utils.build import tar

ROOT = Path(__file__).resolve().parents[2]


def test_build_context_keeps_runtime_and_excludes_secrets(tmp_path: Path) -> None:
    """Nested secrets and local installations must never reach the builder."""
    runtime = {
        "requirements.txt",
        "fonts/Inter.ttf",
        "packages/core/config.py",
        "packages/bot/mini_app/presentation_questionnaire.html",
        "packages/presentation-worker/package.json",
        "packages/presentation-worker/package-lock.json",
        "packages/presentation-worker/src/index.ts",
        "scripts/worker_run_job.py",
        "scripts/healthcheck.py",
        "scripts/backup_db.py",
        "scripts/backup_restore_verify.py",
        "scripts/release_preflight.py",
    }
    private = {
        ".env",
        ".env.production",
        "vertex-key.json",
        "nashr-droplet",
        "packages/core/.env",
        "packages/core/vertex-key.json",
        "packages/core/signing.pem",
        "packages/core/private.key",
        "packages/web/.env.local",
        "packages/web/app/page.tsx",
        "packages/presentation-worker/node_modules/host-binary",
        "packages/presentation-worker/dist/stale.js",
        "packages/core/__pycache__/config.pyc",
        ".git/config",
        "review/auth_bundle.txt",
        "debug/last_deck.json",
        "body.json",
        "scripts/raw/private.json",
        "scripts/_probe_deck_numbers.py",
        "unknown-backup.json",
        "node_modules/host-binary",
    }
    for name in runtime | private:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture", encoding="utf-8")
    rules = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    rules = [rule for rule in rules if rule and not rule.startswith("#")]
    with tar(str(tmp_path), exclude=rules) as archive, tarfile.open(fileobj=archive) as contents:
        included = set(contents.getnames())
    assert runtime <= included
    assert not private & included, sorted(private & included)


def test_dockerfile_does_not_copy_the_repository_root() -> None:
    """Defense in depth: an accidental ignore-file regression cannot copy root secrets."""
    lines = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    copies = [line.split() for line in lines if line.startswith("COPY ")]
    assert all(copy[1] not in {".", "./"} for copy in copies)
