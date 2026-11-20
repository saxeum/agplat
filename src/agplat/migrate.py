"""Apply committed SQL migrations to ``AGPLAT_DB_URL``."""

import asyncio

from agplat.db import migrate
from agplat.settings import get_settings


def main() -> None:
    applied = asyncio.run(migrate(get_settings().db_url))
    if applied:
        print("applied: " + ", ".join(applied))
    else:
        print("database is up to date")


if __name__ == "__main__":  # pragma: no cover
    main()
