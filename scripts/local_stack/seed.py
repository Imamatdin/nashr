"""Seed one user with an article project per locale into the local stack.

Prints a JSON fixture (session + project IDs) for the browser journey. Talks to
the local Postgres container directly; refuses to run against anything else.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parent)]

from local_env import JWT_SECRET  # noqa: E402

from packages.api.services.tokens import mint_app_jwt  # noqa: E402

CONTAINER = "nashr-local-pg"
TITLES = {
    "uz": "Orol dengizi: suv balansi va oqibatlar",
    "ru": "Аральское море: водный баланс и последствия",
    "en": "The Aral Sea: water balance and consequences",
}


def _sql(statement: str) -> None:
    """Run one statement in the local container as the owner."""

    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-q", "-v", "ON_ERROR_STOP=1",
         "-U", "postgres", "-d", "postgres"],
        input=statement.encode(),
        check=True,
    )


def seed() -> dict[str, object]:
    """Create a fresh user, two users' worth of isolation, and one project per locale."""

    user, intruder = uuid.uuid4(), uuid.uuid4()
    telegram = uuid.uuid4().int % 9_000_000_000 + 1_000_000_000
    _sql(
        "insert into users (id, telegram_id, language) values "
        f"('{user}', {telegram}, 'uz'), ('{intruder}', {telegram + 1}, 'ru');"
    )
    projects: dict[str, str] = {}
    for locale, title in TITLES.items():
        project = uuid.uuid4()
        projects[locale] = str(project)
        _sql(
            "insert into projects (id, user_id, type, title, language, audience) values "
            f"('{project}', '{user}', 'article', $t${title}$t$, '{locale}', 'akademik');"
        )
    minted = mint_app_jwt(JWT_SECRET, user, 6 * 3600)
    intruder_token = mint_app_jwt(JWT_SECRET, intruder, 6 * 3600)
    return {
        "session": {
            "accessToken": minted.access_token,
            "expiresAt": minted.expires_at.isoformat(),
            "userId": str(user),
        },
        "intruderToken": intruder_token.access_token,
        "projects": projects,
    }


if __name__ == "__main__":
    print(json.dumps(seed()))
