"""Postgres connection and forward-only SQL migrations."""

from pathlib import Path
from typing import Any

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

SCHEMA_MIGRATIONS = """
create table if not exists schema_migrations (
    name text primary key,
    applied_at timestamptz not null default now()
)
"""


async def migrate(dsn: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply each unapplied ``*.sql`` file in name order; return the names applied."""
    connection = await asyncpg.connect(dsn)
    try:
        return await _apply(connection, directory)
    finally:
        await connection.close()


async def _apply(connection: Any, directory: Path) -> list[str]:
    await connection.execute(SCHEMA_MIGRATIONS)
    applied = {row["name"] for row in await connection.fetch("select name from schema_migrations")}

    newly: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in applied:
            continue
        async with connection.transaction():
            await connection.execute(path.read_text(encoding="utf-8"))
            await connection.execute(
                "insert into schema_migrations (name) values ($1)",
                path.name,
            )
        newly.append(path.name)
    return newly
