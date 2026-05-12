"""Sanity checks for the deployment-config files.

These tests don't run Docker. They assert that the required files exist
on disk, parse cleanly, and reference the keys the bot expects (env
vars, service names, dependencies). Catches drift between
``docker-compose.yml`` / ``.env.example`` / ``requirements.txt`` and the
runtime expectations of :mod:`packages.platform.config`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Files exist
# ---------------------------------------------------------------------------


def test_dockerfile_exists() -> None:
    assert (PROJECT_ROOT / "Dockerfile").is_file()


def test_docker_compose_exists() -> None:
    assert (PROJECT_ROOT / "docker-compose.yml").is_file()


def test_env_example_exists() -> None:
    assert (PROJECT_ROOT / ".env.example").is_file()


def test_requirements_txt_exists() -> None:
    assert (PROJECT_ROOT / "requirements.txt").is_file()


def test_deploy_md_exists() -> None:
    assert (PROJECT_ROOT / "DEPLOY.md").is_file()


# ---------------------------------------------------------------------------
# .env.example contains every required key
# ---------------------------------------------------------------------------


def test_env_example_has_required_vars() -> None:
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "WEBHOOK_URL",
        "R2_ENDPOINT",
        "R2_ACCESS_KEY",
        "R2_SECRET_KEY",
        "R2_BUCKET",
        "REDIS_URL",
    ):
        assert key in text, f".env.example missing {key}"


# ---------------------------------------------------------------------------
# docker-compose.yml shape
# ---------------------------------------------------------------------------


def _load_compose() -> dict[str, Any]:
    raw = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict)
    return cast(dict[str, Any], parsed)


def test_docker_compose_has_bot_service() -> None:
    services = _load_compose().get("services")
    assert isinstance(services, dict)
    assert "bot" in services


def test_docker_compose_has_redis_service() -> None:
    services = _load_compose().get("services")
    assert isinstance(services, dict)
    assert "redis" in services


def test_docker_compose_bot_depends_on_redis() -> None:
    services = cast(dict[str, Any], _load_compose()["services"])
    bot = cast(dict[str, Any], services["bot"])
    depends = bot.get("depends_on")
    assert depends is not None
    if isinstance(depends, dict):
        assert "redis" in depends
    else:
        assert "redis" in cast(list[str], depends)


def test_docker_compose_bot_exposes_8080() -> None:
    services = cast(dict[str, Any], _load_compose()["services"])
    bot = cast(dict[str, Any], services["bot"])
    ports = bot.get("ports")
    assert isinstance(ports, list)
    assert any("8080" in str(item) for item in ports)


def test_docker_compose_redis_healthcheck_present() -> None:
    services = cast(dict[str, Any], _load_compose()["services"])
    redis = cast(dict[str, Any], services["redis"])
    assert isinstance(redis.get("healthcheck"), dict)


# ---------------------------------------------------------------------------
# requirements.txt covers actually-imported packages
# ---------------------------------------------------------------------------


def test_requirements_has_core_deps() -> None:
    text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for dep in (
        "aiogram",
        "anthropic",
        "supabase",
        "boto3",
        "pydantic",
        "google-genai",
        "magika",
        "python-docx",
        "python-pptx",
        "openpyxl",
        "pymupdf",
        "pillow",
        "feedparser",
    ):
        assert dep in text, f"requirements.txt missing {dep}"


# ---------------------------------------------------------------------------
# Dockerfile carries the runtime essentials
# ---------------------------------------------------------------------------


def test_dockerfile_installs_libreoffice() -> None:
    text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8").lower()
    assert "libreoffice-writer" in text


def test_dockerfile_installs_tesseract() -> None:
    text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8").lower()
    assert "tesseract-ocr" in text


def test_dockerfile_installs_node() -> None:
    text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8").lower()
    assert "nodejs" in text or "node_22" in text


def test_dockerfile_exposes_8080() -> None:
    text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "EXPOSE 8080" in text


def test_dockerfile_has_healthcheck() -> None:
    text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in text
    assert "/health" in text
