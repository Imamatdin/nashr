"""CORS allowlist parsing (plan §4 — explicit origins, no wildcard)."""

from __future__ import annotations

from packages.platform.config import _parse_origins


def test_wildcard_origin_is_dropped() -> None:
    # Panel finding: WEB_CORS_ORIGINS=* must not open bearer-auth endpoints to
    # every origin. Wildcard entries are dropped; the contract is an allowlist.
    assert _parse_origins("*") == ()
    assert _parse_origins("https://nashr.uz, *") == ("https://nashr.uz",)


def test_normal_origins_are_kept_and_trimmed() -> None:
    assert _parse_origins("https://a.com/ , https://b.com") == (
        "https://a.com",
        "https://b.com",
    )
    assert _parse_origins("") == ()
