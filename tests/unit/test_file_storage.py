"""Behaviour tests for :class:`packages.platform.storage.FileStorage`.

Two seams:

* The local-fallback path uses the real filesystem under a per-test
  ``$HOME`` so we can assert on copy / read / delete behaviour without
  reaching for R2.
* The R2 path swaps the underlying boto3 client for a :class:`MagicMock`
  via ``monkeypatch``; tests assert that ``FileStorage`` translates its
  public API into the right boto3 method calls.

Following the project testing rules: no mocking of stdlib or local
libraries — only the external R2 boundary is faked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from packages.platform.config import PlatformConfig
from packages.platform.storage import FileStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_local_config() -> PlatformConfig:
    """A config with no R2 credentials — exercises the local fallback path."""

    return PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test",
        telegram_bot_token="test",
    )


def _make_r2_config() -> PlatformConfig:
    """A config with synthetic R2 credentials so the boto3 client is built."""

    return PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test",
        telegram_bot_token="test",
        r2_endpoint="https://acct.r2.cloudflarestorage.com",
        r2_access_key="ak",
        r2_secret_key="sk",
        r2_bucket="nashr-test",
    )


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` so local-fallback writes land in tmp_path."""

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def _patch_boto(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``boto3.client`` so no real client is constructed."""

    from packages.platform import storage as storage_mod

    client = MagicMock(name="r2_client")
    factory = MagicMock(name="boto3_client_factory", return_value=client)
    monkeypatch.setattr(storage_mod.boto3, "client", factory)
    return client


# ---------------------------------------------------------------------------
# Availability flag
# ---------------------------------------------------------------------------


def test_storage_not_available_without_config() -> None:
    storage = FileStorage(_make_local_config())
    assert storage.available is False


def test_storage_available_with_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_boto(monkeypatch)
    storage = FileStorage(_make_r2_config())
    assert storage.available is True
    assert storage.bucket == "nashr-test"


# ---------------------------------------------------------------------------
# Local-fallback round trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_upload(tmp_path: Path) -> None:
    storage = FileStorage(_make_local_config())
    src = tmp_path / "src.txt"
    src.write_bytes(b"hello world")

    key = await storage.upload(src, "generated/proj/article.txt")

    assert key == "generated/proj/article.txt"
    dest = Path.home() / ".nashr" / "storage" / "generated" / "proj" / "article.txt"
    assert dest.read_bytes() == b"hello world"


@pytest.mark.asyncio
async def test_local_download(tmp_path: Path) -> None:
    storage = FileStorage(_make_local_config())
    src = tmp_path / "src.txt"
    src.write_bytes(b"payload")
    await storage.upload(src, "generated/abc/file.txt")

    target = tmp_path / "out" / "file.txt"
    returned = await storage.download("generated/abc/file.txt", target)

    assert returned == target
    assert target.read_bytes() == b"payload"


@pytest.mark.asyncio
async def test_local_get_bytes(tmp_path: Path) -> None:
    storage = FileStorage(_make_local_config())
    src = tmp_path / "src.bin"
    src.write_bytes(b"\x00\x01\x02BLOB")
    await storage.upload(src, "sources/proj/blob.bin")

    fetched = await storage.get_bytes("sources/proj/blob.bin")

    assert fetched == b"\x00\x01\x02BLOB"


@pytest.mark.asyncio
async def test_local_exists(tmp_path: Path) -> None:
    storage = FileStorage(_make_local_config())
    src = tmp_path / "src.txt"
    src.write_bytes(b"x")
    await storage.upload(src, "generated/p/f.txt")

    assert await storage.exists("generated/p/f.txt") is True
    assert await storage.exists("generated/p/missing.txt") is False


@pytest.mark.asyncio
async def test_local_delete(tmp_path: Path) -> None:
    storage = FileStorage(_make_local_config())
    src = tmp_path / "src.txt"
    src.write_bytes(b"x")
    await storage.upload(src, "generated/p/f.txt")
    assert await storage.exists("generated/p/f.txt") is True

    await storage.delete("generated/p/f.txt")

    assert await storage.exists("generated/p/f.txt") is False


@pytest.mark.asyncio
async def test_local_signed_url_returns_file_uri(tmp_path: Path) -> None:
    storage = FileStorage(_make_local_config())
    src = tmp_path / "src.txt"
    src.write_bytes(b"x")
    await storage.upload(src, "generated/p/f.txt")

    url = await storage.signed_url("generated/p/f.txt")

    assert url.startswith("file:///")
    assert url.endswith("/.nashr/storage/generated/p/f.txt")


# ---------------------------------------------------------------------------
# Key builders
# ---------------------------------------------------------------------------


def test_source_key_format() -> None:
    assert FileStorage.source_key("abc123", "paper.pdf") == "sources/abc123/paper.pdf"


def test_generated_key_format() -> None:
    assert FileStorage.generated_key("abc123", "article.docx") == "generated/abc123/article.docx"


def test_key_sanitizes_slashes() -> None:
    key = FileStorage.source_key("abc", "path/to/file.pdf")
    assert key == "sources/abc/path_to_file.pdf"
    assert "/" not in key.split("/", 2)[-1]


def test_key_sanitizes_backslashes() -> None:
    key = FileStorage.source_key("abc", "path\\to\\file.pdf")
    assert key == "sources/abc/path_to_file.pdf"


# ---------------------------------------------------------------------------
# Content-type detection
# ---------------------------------------------------------------------------


def test_guess_content_type() -> None:
    from packages.platform.storage import _guess_content_type

    assert _guess_content_type(Path("a.pdf")) == "application/pdf"
    assert (
        _guess_content_type(Path("a.docx"))
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert _guess_content_type(Path("a.html")) == "text/html"
    assert _guess_content_type(Path("a.unknown")) is None


# ---------------------------------------------------------------------------
# R2 path — verifies boto3 calls are routed correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2_upload_calls_boto3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_boto(monkeypatch)
    storage = FileStorage(_make_r2_config())
    src = tmp_path / "src.pdf"
    src.write_bytes(b"pdf bytes")

    await storage.upload(src, "generated/proj/out.pdf")

    client.upload_file.assert_called_once()
    args, kwargs = client.upload_file.call_args
    assert args[0] == str(src)
    assert args[1] == "nashr-test"
    assert args[2] == "generated/proj/out.pdf"
    assert kwargs.get("ExtraArgs") == {"ContentType": "application/pdf"}


@pytest.mark.asyncio
async def test_r2_download_calls_boto3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_boto(monkeypatch)
    storage = FileStorage(_make_r2_config())
    target = tmp_path / "out" / "f.pdf"

    await storage.download("generated/p/f.pdf", target)

    client.download_file.assert_called_once_with("nashr-test", "generated/p/f.pdf", str(target))


@pytest.mark.asyncio
async def test_r2_signed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_boto(monkeypatch)
    client.generate_presigned_url.return_value = "https://signed.example/x"
    storage = FileStorage(_make_r2_config())

    url = await storage.signed_url("generated/p/f.pdf", expires_in=120)

    assert url == "https://signed.example/x"
    client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "nashr-test", "Key": "generated/p/f.pdf"},
        ExpiresIn=120,
    )


@pytest.mark.asyncio
async def test_r2_delete_calls_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_boto(monkeypatch)
    storage = FileStorage(_make_r2_config())

    await storage.delete("generated/p/f.pdf")

    client.delete_object.assert_called_once_with(Bucket="nashr-test", Key="generated/p/f.pdf")


@pytest.mark.asyncio
async def test_r2_exists_true(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_boto(monkeypatch)
    client.head_object.return_value = {"ContentLength": 1}
    storage = FileStorage(_make_r2_config())

    found = await storage.exists("generated/p/f.pdf")

    assert found is True
    client.head_object.assert_called_once_with(Bucket="nashr-test", Key="generated/p/f.pdf")


@pytest.mark.asyncio
async def test_r2_exists_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_boto(monkeypatch)
    client.head_object.side_effect = RuntimeError("not found")
    storage = FileStorage(_make_r2_config())

    found = await storage.exists("generated/p/missing.pdf")

    assert found is False


@pytest.mark.asyncio
async def test_r2_get_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_boto(monkeypatch)
    body = MagicMock()
    body.read.return_value = b"r2 payload"
    client.get_object.return_value = {"Body": body}
    storage = FileStorage(_make_r2_config())

    data = await storage.get_bytes("generated/p/f.bin")

    assert data == b"r2 payload"
    client.get_object.assert_called_once_with(Bucket="nashr-test", Key="generated/p/f.bin")


def test_r2_client_constructed_with_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.platform import storage as storage_mod

    client = MagicMock(name="r2_client")
    factory = MagicMock(name="boto3_client_factory", return_value=client)
    monkeypatch.setattr(storage_mod.boto3, "client", factory)

    FileStorage(_make_r2_config())

    factory.assert_called_once()
    args, kwargs = factory.call_args
    assert args[0] == "s3"
    assert kwargs.get("endpoint_url") == "https://acct.r2.cloudflarestorage.com"
    assert kwargs.get("aws_access_key_id") == "ak"
    assert kwargs.get("aws_secret_access_key") == "sk"
    assert kwargs.get("region_name") == "auto"
    cfg: Any = kwargs.get("config")
    assert cfg is not None
    assert cfg.signature_version == "s3v4"
