"""Tiny strict-mode helpers for parsing untyped JSON from external APIs.

The four academic providers all face the same problem: ``httpx.Response.json``
returns ``Any``, and once that flows through ``dict.get`` it shows up as
``Unknown`` under pyright strict mode. Centralising the cast boundary here
keeps the providers themselves free of repeated ``cast(dict[str, Any], …)``
incantations.
"""

from __future__ import annotations

from typing import Any, cast


def as_dict(value: object) -> dict[str, Any] | None:
    """Cast ``value`` to ``dict[str, Any]`` if it is a dict, else ``None``."""

    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return None


def as_list(value: object) -> list[Any] | None:
    """Cast ``value`` to ``list[Any]`` if it is a list, else ``None``."""

    if isinstance(value, list):
        return cast(list[Any], value)
    return None
