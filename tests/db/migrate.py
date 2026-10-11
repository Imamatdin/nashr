"""CI helper: create a named database and apply the migration chain to it.

    python -m tests.db.migrate nashr_rest            # all migrations
    python -m tests.db.migrate nashr_old --through 015

Uses ``NASHR_TEST_DATABASE_URL`` (superuser). Prints each applied file.
"""

from __future__ import annotations

import argparse
import asyncio

from tests.db.support import create_database, migrations_through


def main() -> int:
    parser = argparse.ArgumentParser(description="create and migrate a test database")
    parser.add_argument("name")
    parser.add_argument("--through", default=None, help="last migration prefix, e.g. 015")
    args = parser.parse_args()
    files = migrations_through(args.through)
    asyncio.run(create_database(files, args.name))
    for path in files:
        print(f"applied {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
