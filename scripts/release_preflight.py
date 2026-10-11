"""Read-only API and database release probes; never print secrets or response bodies.

Run with environment variables, or explicitly pass --env-file .env. A successful
probe is necessary, not sufficient, for release: SQL constraints, RLS, workers,
model calls, storage, backups, and user journeys still need their own checks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import cast
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator


class ProbeConfig(BaseModel):
    """Explicit trusted endpoints; secrets are excluded from representations."""

    model_config = ConfigDict(extra="forbid")
    api_url: str
    supabase_url: str
    service_key: SecretStr

    @field_validator("api_url", "supabase_url")
    @classmethod
    def secure_origin(cls, value: str) -> str:
        """Only accept HTTPS origins without credentials, paths, or queries."""
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("expected an HTTPS origin")
        return value


class Check(BaseModel):
    """Small safe result suitable for logs and CI artifacts."""

    model_config = ConfigDict(extra="forbid")
    name: str
    ok: bool
    detail: str


def _valid_payload(name: str, payload: object) -> bool:
    """Require expected shapes, not merely a 200 status from a proxy."""
    record = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
    if name == "api":
        return record.get("status") == "ok" and record.get("service") == "nashr-api"
    if name == "document_rpcs":
        paths = record.get("paths")
        expected = {
            "/rpc/ensure_document",
            "/rpc/commit_revision",
            "/rpc/accept_proposal",
            "/rpc/reject_proposal",
            "/rpc/register_export",
        }
        return isinstance(paths, dict) and expected <= paths.keys()
    return isinstance(payload, list) and not payload


async def _probe(client: httpx.AsyncClient, name: str, url: str, headers: dict[str, str]) -> Check:
    """Read one surface with a bounded timeout and no redirect credential forwarding."""
    try:
        response = await client.get(url, headers=headers, timeout=12, follow_redirects=False)
        if response.status_code != 200:
            return Check(name=name, ok=False, detail=f"HTTP {response.status_code}")
        try:
            payload: object = response.json()
        except ValueError:
            return Check(name=name, ok=False, detail="Unexpected response")
        valid = _valid_payload(name, payload)
        return Check(name=name, ok=valid, detail="Verified" if valid else "Unexpected response")
    except httpx.HTTPError as exc:
        return Check(name=name, ok=False, detail=type(exc).__name__)


async def run_checks(config: ProbeConfig, client: httpx.AsyncClient) -> list[Check]:
    """Inspect schema visibility without reading user rows or invoking mutations."""
    key = config.service_key.get_secret_value()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    base = config.supabase_url + "/rest/v1/"
    targets: list[tuple[str, str, dict[str, str]]] = [
        ("api", config.api_url + "/health", {}),
        ("database", base + "projects?select=id&limit=0", headers),
        ("documents", base + "documents?select=id,head_revision_id&limit=0", headers),
        ("revisions", base + "document_revisions?select=id,parent_revision_id&limit=0", headers),
        ("document_rpcs", base, {**headers, "Accept": "application/openapi+json"}),
    ]
    return list(await asyncio.gather(*(_probe(client, *target) for target in targets)))


async def _run(config: ProbeConfig) -> int:
    """Print structured sanitized checks and return a nonzero exit on failure."""
    async with httpx.AsyncClient() as client:
        checks = await run_checks(config, client)
    print(json.dumps({"checks": [check.model_dump() for check in checks]}, indent=2))
    return 0 if all(check.ok for check in checks) else 1


def main() -> int:
    """Load explicit config without echoing validation inputs or credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="optional dotenv file; process environment wins")
    parser.add_argument("--api-url", default="https://api.nashr.com.uz")
    args = parser.parse_args()
    values = {**(dotenv_values(args.env_file) if args.env_file else {}), **os.environ}
    try:
        config = ProbeConfig(
            api_url=args.api_url,
            supabase_url=values.get("SUPABASE_URL") or "",
            service_key=SecretStr(values.get("SUPABASE_SERVICE_KEY") or ""),
        )
        if not config.service_key.get_secret_value().strip():
            raise ValueError("missing key")
    except ValueError:
        print("Configuration invalid: supply HTTPS origins and SUPABASE_SERVICE_KEY.")
        return 2
    return asyncio.run(_run(config))


if __name__ == "__main__":
    raise SystemExit(main())
