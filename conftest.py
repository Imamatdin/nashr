"""Project-root conftest: makes ``packages`` importable when running pytest from any cwd."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _no_brain_cache_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: a dev shell exporting GEMINI_BRAIN_CACHE=1 must not
    make fake-Gemini driver tests hit the real caches.create API. Tests that
    exercise the flag set it explicitly after this fixture clears it."""

    monkeypatch.delenv("GEMINI_BRAIN_CACHE", raising=False)
