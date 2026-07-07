"""P1 identity-path preflight: can a self-minted HS256 JWT drive PostgREST AND Realtime?

Decides plan §5's Path A vs Path B fork (amendment 4: BOTH surfaces must accept
the minted token — Realtime validates tokens on its own path, and the web UI
depends on it for job progress and deck updates). NOT RUN by the autorun that
wrote it; the human runs it once against the real Supabase project.

    python scripts/preflight_identity_path.py

Required env (never invented; .env is loaded if python-dotenv is present):
    SUPABASE_URL          https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY  service-role key (row setup + the trigger write only)
    SUPABASE_ANON_KEY     anon/publishable key (the client apikey surface)
    SUPABASE_JWT_SECRET   the project's LEGACY shared JWT secret
                          (Dashboard -> Settings -> API -> JWT secret). If the
                          project uses asymmetric signing keys ONLY and exposes
                          no shared secret, Path B is already decided - record
                          it and skip this probe.
Optional env:
    PREFLIGHT_TEST_USER_ID  existing users.id to run as; otherwise a throwaway
                            user + project are created and deleted afterwards.

Exit codes:
    0  PATH A — PostgREST returned the owner row AND a Realtime postgres_changes
       event arrived on a channel authorized with the minted JWT.
    2  PATH B — one or both checks failed; stdout names WHICH check and the
       likeliest cause (bad signature vs RLS mismatch vs missing publication).
    3  configuration error (missing env, setup failure) — decides nothing.

The Realtime check needs `projects` in the `supabase_realtime` publication
(Dashboard -> Database -> Replication). A JOIN that succeeds but times out
waiting for the event is reported as PUBLICATION-MISSING, not as a token
failure - fix the publication and re-run rather than concluding Path B.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import enum
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # optional; env may be exported directly
    pass

_JWT_TTL_SECONDS = 600
_EVENT_TIMEOUT_SECONDS = 15.0


class RealtimeResult(enum.Enum):
    """Three-way Realtime check outcome (a bool conflated REJECT with INCONCLUSIVE)."""

    PASS = "pass"  # event delivered → the minted token drives Realtime
    REJECT = "reject"  # token refused at join → Path B evidence
    INCONCLUSIVE = "inconclusive"  # joined-but-no-event / connectivity → fix & re-run


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_supabase_jwt(secret: str, sub: str) -> str:
    """Mint the exact HS256 JWT shape Path A's backend would issue (stdlib only)."""

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": sub,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": now,
        "exp": now + _JWT_TTL_SECONDS,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _require_env(names: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            values[name] = value
        else:
            missing.append(name)
    if missing:
        print(f"CONFIG ERROR: missing env {', '.join(missing)} — decides nothing.")
        sys.exit(3)
    return values


class _ServiceApi:
    """Minimal service-role PostgREST wrapper for setup/trigger/cleanup."""

    def __init__(self, url: str, service_key: str) -> None:
        self._rest = f"{url.rstrip('/')}/rest/v1"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    async def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self._rest}/{table}", headers=self._headers, json=row)
        response.raise_for_status()
        return response.json()[0]

    async def update(self, table: str, row_id: str, patch: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.patch(
                f"{self._rest}/{table}?id=eq.{row_id}", headers=self._headers, json=patch
            )
        response.raise_for_status()

    async def delete(self, table: str, row_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(
                f"{self._rest}/{table}?id=eq.{row_id}", headers=self._headers
            )
        # raise on failure (panel finding): a swallowed non-2xx would silently
        # strand a throwaway row under a real user (PREFLIGHT_TEST_USER_ID case).
        response.raise_for_status()


async def _check_postgrest(
    url: str, anon_key: str, minted_jwt: str, project_id: str
) -> tuple[bool, str]:
    """Check 1: an RLS'd owner read through PostgREST with the minted token."""

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{url.rstrip('/')}/rest/v1/projects",
            params={"select": "id", "id": f"eq.{project_id}"},
            headers={"apikey": anon_key, "Authorization": f"Bearer {minted_jwt}"},
        )
    if response.status_code in (401, 403):
        return False, (
            f"PostgREST rejected the minted token (HTTP {response.status_code}: "
            f"{response.text[:200]}) — signature not accepted; likeliest asymmetric-"
            "signing-only project or wrong SUPABASE_JWT_SECRET."
        )
    if response.status_code != 200:
        return False, f"PostgREST unexpected HTTP {response.status_code}: {response.text[:200]}"
    rows = response.json()
    if not rows:
        return False, (
            "PostgREST ACCEPTED the token (HTTP 200) but returned zero rows — the "
            "policies did not match sub=users.id. Verify the test project belongs "
            "to the sub user; if it does, Path A's premise fails → Path B."
        )
    return True, f"PostgREST returned the owner row (HTTP 200, {len(rows)} row)."


async def _check_realtime(
    url: str,
    anon_key: str,
    minted_jwt: str,
    project_id: str,
    service: _ServiceApi,
) -> tuple[RealtimeResult, str]:
    """Check 2: a postgres_changes event on a channel authorized with the minted JWT.

    Returns one of THREE outcomes (panel finding — a bool conflated two of them):
    PASS (event delivered), REJECT (the token was refused → Path B evidence), or
    INCONCLUSIVE (joined but no event, likeliest a missing `supabase_realtime`
    publication — NOT a Path B decision; fix and re-run). A connect/handshake
    failure also maps to INCONCLUSIVE rather than escaping as an uncontracted
    traceback.
    """

    from realtime import RealtimePostgresChangesListenEvent  # deferred with supabase

    from supabase import acreate_client  # deferred: import cost + optional surface

    client = await acreate_client(url, anon_key)
    joined: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    got_event: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    def _on_event(_payload: object) -> None:
        if not got_event.done():
            got_event.set_result(True)

    def _on_subscribe(status: object, err: object) -> None:
        if not joined.done():
            joined.set_result(f"{status}{f' err={err}' if err else ''}")

    try:
        try:
            await client.realtime.set_auth(minted_jwt)
            channel = client.channel("preflight-identity")
            channel.on_postgres_changes(
                event=RealtimePostgresChangesListenEvent.Update,
                schema="public",
                table="projects",
                filter=f"id=eq.{project_id}",
                callback=_on_event,
            )
            # subscribe() connects before joining and can raise on a network/TLS
            # failure (panel finding) — that is a connectivity fault, not a token
            # verdict, so it maps to INCONCLUSIVE, never an uncaught exit 1.
            await channel.subscribe(_on_subscribe)
        except Exception as exc:
            return RealtimeResult.INCONCLUSIVE, (
                f"Realtime connect/subscribe failed before any join ({type(exc).__name__}: "
                f"{exc}). Connectivity/config problem — decides nothing; fix and re-run."
            )
        try:
            join_status = await asyncio.wait_for(joined, timeout=_EVENT_TIMEOUT_SECONDS)
        except TimeoutError:
            return RealtimeResult.INCONCLUSIVE, (
                "Realtime JOIN timed out — connectivity problem, not a token verdict; "
                "decides nothing, fix and re-run."
            )
        if "SUBSCRIBED" not in str(join_status).upper():
            return RealtimeResult.REJECT, (
                f"Realtime channel join failed ({join_status}) with the minted token — "
                "Realtime rejected what PostgREST may have accepted; per amendment 4 "
                "this alone decides Path B."
            )
        await service.update("projects", project_id, {"title": f"preflight {uuid.uuid4().hex[:8]}"})
        try:
            await asyncio.wait_for(got_event, timeout=_EVENT_TIMEOUT_SECONDS)
        except TimeoutError:
            return RealtimeResult.INCONCLUSIVE, (
                "Realtime JOINED (token accepted) but no postgres_changes event arrived in "
                f"{_EVENT_TIMEOUT_SECONDS:.0f}s. Likeliest `projects` is missing from the "
                "supabase_realtime publication — FIX THE PUBLICATION AND RE-RUN. This is "
                "NOT Path B: the JOIN proves the token was accepted."
            )
        return (
            RealtimeResult.PASS,
            "Realtime delivered the owner-row UPDATE event on the minted-JWT channel.",
        )
    finally:
        # Teardown must not mask the verdict.
        with contextlib.suppress(Exception):
            await client.realtime.close()


async def main() -> None:
    env = _require_env(
        ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_JWT_SECRET"]
    )
    service = _ServiceApi(env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"])

    provided_user = os.environ.get("PREFLIGHT_TEST_USER_ID", "").strip()
    created_user_id: str | None = None
    project_id: str | None = None
    # Default INCONCLUSIVE: any exception that unwinds past the try supersedes
    # sys.exit anyway; this only keeps the happy-path exit total.
    _verdict_exit = 3
    try:
        if provided_user:
            user_id = provided_user
        else:
            try:
                user = await service.insert(
                    "users",
                    {
                        "telegram_id": int(time.time() * 1000) % 9_000_000_000 + 1,
                        "language": "uz",
                        "subscriber_id": str(100000 + int(time.time()) % 899999),
                    },
                )
            except httpx.HTTPStatusError as exc:
                print(f"CONFIG ERROR: could not create throwaway user: {exc}")
                sys.exit(3)
            user_id = created_user_id = user["id"]
        try:
            project = await service.insert(
                "projects",
                {
                    "user_id": user_id,
                    "type": "presentation",
                    "title": "identity preflight",
                    "language": "uz",
                    "audience": "talaba",
                },
            )
        except httpx.HTTPStatusError as exc:
            print(
                "CONFIG ERROR: could not create probe project (check projects NOT NULL/"
                f"CHECK columns and adjust the insert): {exc}"
            )
            sys.exit(3)
        probe_project_id: str = str(project["id"])
        project_id = probe_project_id

        minted = mint_supabase_jwt(env["SUPABASE_JWT_SECRET"], sub=user_id)
        print(f"minted JWT for sub={user_id} (exp +{_JWT_TTL_SECONDS}s)")

        rest_ok, rest_msg = await _check_postgrest(
            env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"], minted, probe_project_id
        )
        print(f"[check 1 — PostgREST] {'PASS' if rest_ok else 'FAIL'}: {rest_msg}")

        realtime_result, realtime_msg = await _check_realtime(
            env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"], minted, probe_project_id, service
        )
        print(f"[check 2 — Realtime ] {realtime_result.value.upper()}: {realtime_msg}")

        # INCONCLUSIVE Realtime decides NOTHING (panel finding): a missing
        # publication or a connectivity fault must NOT be read as Path B — exit 3
        # so the operator fixes it and re-runs rather than applying 005b wrongly.
        if realtime_result is RealtimeResult.INCONCLUSIVE:
            print(
                "\nVERDICT: INCONCLUSIVE — the Realtime check could not decide (see above). "
                "This is NOT Path B. Fix the cause and re-run before choosing a path."
            )
            _verdict_exit = 3
        elif rest_ok and realtime_result is RealtimeResult.PASS:
            print("\nVERDICT: PATH A — mint HS256 JWTs with sub=users.id; apply 005 only.")
            _verdict_exit = 0
        else:
            print(
                "\nVERDICT: PATH B — apply 005 AND 005b (app_uid() policy rewrite), use real "
                "Supabase sessions. No debate mid-build (amendment 4)."
            )
            _verdict_exit = 2
    finally:
        # Cleanup runs on every path but must NEVER mask the verdict exit code
        # (panel finding): a failed DELETE here previously overrode SystemExit(0)
        # into a traceback/exit 1, and a project-delete failure skipped the user
        # delete. Both deletes are attempted; failures are surfaced as warnings.
        if project_id:
            try:
                await service.delete("projects", project_id)
            except Exception as exc:
                print(f"WARNING: probe project {project_id} cleanup failed: {exc}")
        if created_user_id:
            try:
                await service.delete("users", created_user_id)
            except Exception as exc:
                print(f"WARNING: probe user {created_user_id} cleanup failed: {exc}")
    sys.exit(_verdict_exit)


if __name__ == "__main__":
    asyncio.run(main())
