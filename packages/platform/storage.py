"""File storage client backed by Cloudflare R2 (S3-compatible).

Stores every persistent artefact the platform produces: uploaded source
files and generated outputs (DOCX / PDF / HTML / PPTX). The database
keeps the R2 key (path within the bucket); downloads go through signed
URLs or direct ``get_object`` calls.

Layout::

    sources/{project_id}/{filename}      uploaded source files
    generated/{project_id}/{filename}    rendered outputs
    temp/{project_id}/{filename}         intermediate processing files

The boto3 S3 client has no first-class type stubs, so the underlying
``self._client`` is typed as ``Any`` at the boundary — the only
legitimate use of ``Any`` here per CLAUDE.md. Local-fallback mode kicks
in automatically when R2 credentials are missing: every file lands in
``~/.nashr/storage/`` so the bot can be exercised end-to-end without an
R2 account during development.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import boto3  # pyright: ignore[reportMissingTypeStubs]
from botocore.config import Config as BotoConfig  # pyright: ignore[reportMissingTypeStubs]

from packages.platform.config import PlatformConfig

logger = logging.getLogger("nashr.storage")

_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".html": "text/html",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class FileStorage:
    """Cloudflare R2 file storage with a local-filesystem fallback.

    Constructed once at bot startup and shared across orchestrators.
    Tests inject configs with empty R2 credentials to exercise the local
    fallback without hitting the network; an R2-aware test mocks
    :func:`boto3.client` and asserts on the recorded calls.
    """

    def __init__(self, config: PlatformConfig) -> None:
        self._bucket = config.r2_bucket
        self._config = config
        self._client: Any
        if config.r2_endpoint and config.r2_access_key and config.r2_secret_key:
            self._client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
                "s3",
                endpoint_url=config.r2_endpoint,
                aws_access_key_id=config.r2_access_key,
                aws_secret_access_key=config.r2_secret_key,
                config=BotoConfig(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
                region_name="auto",
            )
            self._available = True
        else:
            self._client = None
            self._available = False
            logger.warning("R2 not configured. File storage will use local filesystem.")

    @property
    def available(self) -> bool:
        """Whether R2 storage is configured and ready for use."""

        return self._available

    @property
    def bucket(self) -> str:
        """The R2 bucket name (also used as a prefix in error messages)."""

        return self._bucket

    # ============================================================ public ops

    async def upload(
        self,
        local_path: Path,
        remote_key: str,
        content_type: str | None = None,
    ) -> str:
        """Upload ``local_path`` to ``remote_key`` and return the key.

        When R2 is unavailable, a copy is written under
        ``~/.nashr/storage/{remote_key}`` so the rest of the pipeline can
        keep treating the returned key as a stable handle.
        """

        if not self._available:
            return await self._local_upload(local_path, remote_key)

        ctype = content_type if content_type is not None else _guess_content_type(local_path)
        extra: dict[str, str] = {"ContentType": ctype} if ctype else {}

        await asyncio.to_thread(
            self._client.upload_file,
            str(local_path),
            self._bucket,
            remote_key,
            ExtraArgs=extra or None,
        )
        logger.info("storage_upload bucket=%s key=%s", self._bucket, remote_key)
        return remote_key

    async def download(self, remote_key: str, local_path: Path) -> Path:
        """Download ``remote_key`` to ``local_path`` and return that path."""

        if not self._available:
            return await self._local_download(remote_key, local_path)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            self._client.download_file,
            self._bucket,
            remote_key,
            str(local_path),
        )
        logger.info("storage_download bucket=%s key=%s", self._bucket, remote_key)
        return local_path

    async def get_bytes(self, remote_key: str) -> bytes:
        """Return the file at ``remote_key`` as a bytes blob."""

        if not self._available:
            return await self._local_get_bytes(remote_key)

        response: Any = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self._bucket,
            Key=remote_key,
        )
        body: Any = response["Body"]
        data = body.read()
        if not isinstance(data, bytes):
            raise RuntimeError(f"unexpected body type from R2: {type(data).__name__}")
        return data

    async def signed_url(
        self,
        remote_key: str,
        expires_in: int = 3600,
    ) -> str:
        """Generate a pre-signed HTTPS URL for downloading ``remote_key``.

        ``expires_in`` is seconds (default 1 hour). When R2 is not
        configured, a ``file://`` URL into the local fallback dir is
        returned so callers in dev still get a working handle.
        """

        if not self._available:
            return f"file:///{(self._local_storage_dir / remote_key).as_posix()}"

        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": remote_key},
            ExpiresIn=expires_in,
        )
        if not isinstance(url, str):
            raise RuntimeError("R2 signed URL was not a string")
        return url

    async def delete(self, remote_key: str) -> None:
        """Delete the file at ``remote_key``."""

        if not self._available:
            await self._local_delete(remote_key)
            return

        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self._bucket,
            Key=remote_key,
        )
        logger.info("storage_delete bucket=%s key=%s", self._bucket, remote_key)

    async def exists(self, remote_key: str) -> bool:
        """Return whether a file exists at ``remote_key``."""

        if not self._available:
            return (self._local_storage_dir / remote_key).exists()

        try:
            await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=remote_key,
            )
            return True
        except Exception:
            return False

    # ============================================================ key builders

    @staticmethod
    def source_key(project_id: str, filename: str) -> str:
        """Compose the R2 key for an uploaded source file.

        Forward and backward slashes in the user-supplied filename are
        replaced with underscores so the key stays single-segment after
        the ``sources/{project_id}/`` prefix.
        """

        return f"sources/{project_id}/{_sanitize_filename(filename)}"

    @staticmethod
    def generated_key(project_id: str, filename: str) -> str:
        """Compose the R2 key for a generated output file."""

        return f"generated/{project_id}/{_sanitize_filename(filename)}"

    # ============================================================ local fallback

    @property
    def _local_storage_dir(self) -> Path:
        """Root directory used when R2 is not configured."""

        directory = Path.home() / ".nashr" / "storage"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    async def _local_upload(self, local_path: Path, remote_key: str) -> str:
        dest = self._local_storage_dir / remote_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, str(local_path), str(dest))
        logger.info("storage_local_upload key=%s -> %s", remote_key, dest)
        return remote_key

    async def _local_download(self, remote_key: str, local_path: Path) -> Path:
        src = self._local_storage_dir / remote_key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, str(src), str(local_path))
        return local_path

    async def _local_get_bytes(self, remote_key: str) -> bytes:
        src = self._local_storage_dir / remote_key
        return await asyncio.to_thread(src.read_bytes)

    async def _local_delete(self, remote_key: str) -> None:
        src = self._local_storage_dir / remote_key
        await asyncio.to_thread(src.unlink, missing_ok=True)


def _sanitize_filename(name: str) -> str:
    """Strip path separators so a user filename stays a single segment."""

    return name.replace("/", "_").replace("\\", "_")


def _guess_content_type(path: Path) -> str | None:
    """Best-effort MIME type lookup from the file extension."""

    return _CONTENT_TYPES.get(path.suffix.lower())


__all__ = ["FileStorage"]
