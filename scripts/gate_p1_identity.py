"""P1 gate: cross-user RLS isolation under a real app-minted session (plan §7).

The P1 done-gate — proves the identity anchor + migration 005 actually enforce
per-user isolation, not just that the code compiles. Live: seeds TWO throwaway
users each with a project (service role), mints an APP session JWT for user A
via the REAL production mint (``packages.api.services.tokens.mint_app_jwt``),
then reads ``projects`` through RLS'd PostgREST as A and asserts:

  * A sees its OWN project (the policy is not deny-all), AND
  * A sees ZERO of B's rows (the policy is not allow-all).

Either failure is a hard gate failure. This is the Path A shape (the app mints
``sub = users.id``); if the preflight chose Path B, run this against the DEPLOYED
app issuing real Supabase sessions instead — the negative assertion is identical.

Run (needs migration 005 already applied):

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... SUPABASE_ANON_KEY=... \
    SUPABASE_JWT_SECRET=... python scripts/gate_p1_identity.py

Exit 0 = isolation holds. 1 = a violation (details printed). 3 = setup/config
error (decides nothing). Throwaway rows are always cleaned up.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402

from packages.api.services.tokens import mint_app_jwt  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # optional
    pass


def _require_env() -> dict[str, str]:
    names = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_JWT_SECRET"]
    out: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        value = os.environ.get(name, "").strip()
        (out.__setitem__(name, value) if value else missing.append(name))
    if missing:
        print(f"CONFIG ERROR: missing env {', '.join(missing)} — decides nothing.")
        sys.exit(3)
    return out


class _ServiceApi:
    """Service-role PostgREST writes for seeding and cleanup."""

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

    async def delete(self, table: str, row_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(
                f"{self._rest}/{table}?id=eq.{row_id}", headers=self._headers
            )
        response.raise_for_status()


async def _seed_user_with_project(
    service: _ServiceApi, label: str, cleanup: list[tuple[str, str]]
) -> tuple[str, str]:
    """Create a throwaway user + one project; return (user_id, project_id).

    Each created row is appended to ``cleanup`` the moment it exists (review
    finding): a project-insert failure AFTER the user insert must still leave
    the user removable, so the gate never pollutes the live DB on a partial seed.
    """

    stamp = int(time.time() * 1000)
    user = await service.insert(
        "users",
        {
            "telegram_id": stamp % 9_000_000_000 + (1 if label == "A" else 2),
            "language": "uz",
            "subscriber_id": str(100000 + (stamp + (0 if label == "A" else 1)) % 899999),
        },
    )
    cleanup.append(("users", str(user["id"])))
    project = await service.insert(
        "projects",
        {
            "user_id": user["id"],
            "type": "presentation",
            "title": f"p1 gate {label}",
            "language": "uz",
            "audience": "talaba",
        },
    )
    cleanup.append(("projects", str(project["id"])))
    return str(user["id"]), str(project["id"])


async def _projects_visible_to(url: str, anon_key: str, token: str) -> set[str]:
    """Return the set of project ids the bearer token can SELECT through RLS."""

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{url.rstrip('/')}/rest/v1/projects",
            params={"select": "id"},
            headers={"apikey": anon_key, "Authorization": f"Bearer {token}"},
        )
    response.raise_for_status()
    return {row["id"] for row in response.json()}


async def main() -> None:
    env = _require_env()
    service = _ServiceApi(env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"])

    # Every seeded row is recorded here as it is created, so a partial-seed
    # failure still cleans up fully (review finding). _exit defaults to the
    # config-error code; a seed failure leaves it there and skips the check via
    # the `seeded` guard, so control always reaches sys.exit(_exit) below.
    cleanup: list[tuple[str, str]] = []
    _exit = 3
    a_user = a_project = b_project = ""
    seeded = False
    try:
        try:
            a_user, a_project = await _seed_user_with_project(service, "A", cleanup)
            _b_user, b_project = await _seed_user_with_project(service, "B", cleanup)
            seeded = True
        except httpx.HTTPStatusError as exc:
            print(f"CONFIG ERROR: could not seed users/projects: {exc}")

        if seeded:
            token_a = mint_app_jwt(env["SUPABASE_JWT_SECRET"], UUID(a_user), 600).access_token
            visible = await _projects_visible_to(
                env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"], token_a
            )

            sees_own = a_project in visible
            sees_others = b_project in visible

            print(f"[A sees its own project ] {'PASS' if sees_own else 'FAIL'}")
            print(f"[A blocked from B's rows ] {'PASS' if not sees_others else 'FAIL'}")

            if sees_own and not sees_others:
                print("\nGATE PASS: RLS isolates users under a real app-minted session.")
                _exit = 0
            else:
                if not sees_own:
                    print("\nVIOLATION: A cannot read its OWN project — policy denies the owner.")
                if sees_others:
                    print("\nVIOLATION: A can read B's project — RLS is not isolating users.")
                _exit = 1
    finally:
        # Delete projects before users (FK), newest first.
        for table, row_id in sorted(cleanup, key=lambda r: r[0] != "projects"):
            try:
                await service.delete(table, row_id)
            except Exception as exc:
                print(f"WARNING: cleanup of {table} {row_id} failed: {exc}")
    sys.exit(_exit)


if __name__ == "__main__":
    asyncio.run(main())
