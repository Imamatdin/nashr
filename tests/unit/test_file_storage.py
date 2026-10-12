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


@pytest.mark.asyncio
async def test_limited_r2_read_closes_stream_on_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker cannot download unbounded data from a subsequently changed object."""

    from io import BytesIO

    client = _patch_boto(monkeypatch)
    stream = BytesIO(b"too much data")
    client.get_object.return_value = {"Body": stream}
    storage = FileStorage(_make_r2_config())
    with pytest.raises(ValueError, match="source_file_limit"):
        await storage.get_bytes_limited("upload.txt", 4)
    assert stream.closed


@pytest.mark.asyncio
async def test_limited_r2_read_accepts_exact_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from io import BytesIO

    client = _patch_boto(monkeypatch)
    stream = BytesIO(b"four")
    client.get_object.return_value = {"Body": stream}
    storage = FileStorage(_make_r2_config())
    assert await storage.get_bytes_limited("upload.txt", 4) == b"four"
    assert stream.closed


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


def test_upload_source_key_format_and_sanitization() -> None:
    key = FileStorage.upload_source_key("user-1", "deadbeef", "path/to/my file.pdf")
    assert key == "uploads/user-1/deadbeef/path_to_my file.pdf"


@pytest.mark.asyncio
async def test_local_object_size_and_missing(tmp_path: Path) -> None:
    storage = FileStorage(_make_local_config())
    src = tmp_path / "src.txt"
    src.write_bytes(b"12345")
    await storage.upload(src, "uploads/u/x/src.txt")

    assert await storage.object_size("uploads/u/x/src.txt") == 5
    assert await storage.object_size("uploads/u/x/absent.txt") is None


@pytest.mark.asyncio
async def test_presigned_put_requires_r2() -> None:
    storage = FileStorage(_make_local_config())
    with pytest.raises(RuntimeError, match="R2 not configured"):
        await storage.presigned_put_url("uploads/u/x/a.pdf", "application/pdf")


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


# ---------------------------------------------------------------------------
# verified export uploads (ADR 0001)
# ---------------------------------------------------------------------------


def _digest(data: bytes) -> tuple[str, str]:
    import base64
    import hashlib

    raw = hashlib.sha256(data).digest()
    return raw.hex(), base64.b64encode(raw).decode("ascii")


@pytest.mark.asyncio
async def test_local_put_verified_stores_and_proves_the_bytes(
    tmp_path: Path, _isolate_home: Path
) -> None:
    source = tmp_path / "deck.html"
    source.write_bytes(b"<h1>deck</h1>")
    sha_hex, _ = _digest(b"<h1>deck</h1>")
    storage = FileStorage(_make_local_config())

    await storage.put_verified(source, "exports/d/r/v/html/x.html", sha_hex, 13)

    head = await storage.head_object("exports/d/r/v/html/x.html")
    assert head is not None and head.size == 13


@pytest.mark.asyncio
async def test_put_verified_refuses_a_file_that_changed_before_upload(
    tmp_path: Path, _isolate_home: Path
) -> None:
    from packages.platform.storage import StorageVerificationError

    source = tmp_path / "deck.html"
    source.write_bytes(b"changed")
    sha_hex, _ = _digest(b"original")
    storage = FileStorage(_make_local_config())

    with pytest.raises(StorageVerificationError):
        await storage.put_verified(source, "exports/k.html", sha_hex, 8)
    assert await storage.head_object("exports/k.html") is None


@pytest.mark.asyncio
async def test_r2_put_verified_sends_the_checksum_and_checks_the_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _patch_boto(monkeypatch)
    source = tmp_path / "deck.pdf"
    source.write_bytes(b"%PDF")
    sha_hex, sha_b64 = _digest(b"%PDF")
    client.head_object.return_value = {
        "ContentLength": 4,
        "ChecksumSHA256": sha_b64,
        "LastModified": __import__("datetime").datetime(2026, 1, 1),
    }
    storage = FileStorage(_make_r2_config())

    await storage.put_verified(source, "exports/k.pdf", sha_hex, 4)

    put = client.put_object.call_args.kwargs
    assert put["ChecksumSHA256"] == sha_b64 and put["Key"] == "exports/k.pdf"
    assert client.head_object.call_args.kwargs["ChecksumMode"] == "ENABLED"
    client.get_object.assert_not_called()


@pytest.mark.asyncio
async def test_r2_put_verified_fails_on_a_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.platform.storage import StorageVerificationError

    client = _patch_boto(monkeypatch)
    source = tmp_path / "deck.pdf"
    source.write_bytes(b"%PDF")
    sha_hex, _ = _digest(b"%PDF")
    _, other_b64 = _digest(b"something else")
    client.head_object.return_value = {
        "ContentLength": 4,
        "ChecksumSHA256": other_b64,
        "LastModified": __import__("datetime").datetime(2026, 1, 1),
    }
    storage = FileStorage(_make_r2_config())

    with pytest.raises(StorageVerificationError, match="checksum"):
        await storage.put_verified(source, "exports/k.pdf", sha_hex, 4)


@pytest.mark.asyncio
async def test_r2_without_a_reported_checksum_downloads_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import BytesIO

    from packages.platform.storage import StorageVerificationError

    client = _patch_boto(monkeypatch)
    source = tmp_path / "deck.pdf"
    source.write_bytes(b"%PDF")
    sha_hex, _ = _digest(b"%PDF")
    client.head_object.return_value = {
        "ContentLength": 4,
        "LastModified": __import__("datetime").datetime(2026, 1, 1),
    }
    client.get_object.return_value = {"Body": BytesIO(b"%PDX")}
    storage = FileStorage(_make_r2_config())

    with pytest.raises(StorageVerificationError, match="bytes"):
        await storage.put_verified(source, "exports/k.pdf", sha_hex, 4)
    client.get_object.assert_called_once()


def _client_error(code: str, status: int) -> Any:
    from botocore.exceptions import ClientError  # pyright: ignore[reportMissingTypeStubs]

    return ClientError(
        {"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "PutObject",
    )


@pytest.mark.asyncio
async def test_a_store_that_rejects_checksum_put_still_gets_verified_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import BytesIO

    client = _patch_boto(monkeypatch)
    source = tmp_path / "deck.pdf"
    source.write_bytes(b"%PDF")
    sha_hex, _ = _digest(b"%PDF")
    calls: list[dict[str, Any]] = []

    def put_object(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if "ChecksumSHA256" in kwargs:
            raise _client_error("NotImplemented", 501)
        return {}

    client.put_object.side_effect = put_object
    client.head_object.return_value = {
        "ContentLength": 4,
        "LastModified": __import__("datetime").datetime(2026, 1, 1),
    }
    client.get_object.return_value = {"Body": BytesIO(b"%PDF")}
    storage = FileStorage(_make_r2_config())

    await storage.put_verified(source, "exports/k.pdf", sha_hex, 4)

    assert ["ChecksumSHA256" in call for call in calls] == [True, False]
    client.get_object.assert_called_once()  # verified by download and hash


@pytest.mark.asyncio
async def test_a_store_that_rejects_checksum_mode_on_head_falls_back_to_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import BytesIO

    from packages.platform.storage import StorageVerificationError

    client = _patch_boto(monkeypatch)
    source = tmp_path / "deck.pdf"
    source.write_bytes(b"%PDF")
    sha_hex, _ = _digest(b"%PDF")
    heads: list[dict[str, Any]] = []

    def head_object(**kwargs: Any) -> dict[str, Any]:
        heads.append(kwargs)
        if "ChecksumMode" in kwargs:
            raise _client_error("InvalidArgument", 400)
        return {"ContentLength": 4, "LastModified": __import__("datetime").datetime(2026, 1, 1)}

    client.head_object.side_effect = head_object
    client.get_object.return_value = {"Body": BytesIO(b"%PDX")}  # the stored bytes differ
    storage = FileStorage(_make_r2_config())

    with pytest.raises(StorageVerificationError, match="bytes"):
        await storage.put_verified(source, "exports/k.pdf", sha_hex, 4)
    assert ["ChecksumMode" in head for head in heads] == [True, False]


@pytest.mark.asyncio
async def test_a_rejected_digest_is_a_failure_not_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError  # pyright: ignore[reportMissingTypeStubs]

    client = _patch_boto(monkeypatch)
    source = tmp_path / "deck.pdf"
    source.write_bytes(b"%PDF")
    sha_hex, _ = _digest(b"%PDF")
    client.put_object.side_effect = _client_error("BadDigest", 400)
    storage = FileStorage(_make_r2_config())

    with pytest.raises(ClientError):
        await storage.put_verified(source, "exports/k.pdf", sha_hex, 4)
    assert client.put_object.call_count == 1
