"""Integration tests: host pytest against the compose Postgres."""

import asyncio

import asyncpg
import pytest

pytestmark = pytest.mark.integration


def test_database_and_migrations_are_reachable(db_url: str) -> None:
    async def check() -> tuple[int | None, bool | None]:
        connection = await asyncpg.connect(db_url)
        try:
            return (
                await connection.fetchval("select 1"),
                await connection.fetchval(
                    "select to_regclass('public.schema_migrations') is not null"
                ),
            )
        finally:
            await connection.close()

    assert asyncio.run(check()) == (1, True)
