"""Integration tests: host pytest against the compose Postgres."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest

from agplat.runs import RunRepository

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


def test_run_repository_round_trips(db_url: str) -> None:
    async def scenario() -> None:
        repository = RunRepository(db_url)

        run_id = uuid4().hex
        await repository.create_running(
            run_id,
            agent="assistant",
            manifest_digest="digest",
            input="hello",
        )
        running = await repository.get(run_id)
        assert running is not None
        assert running.status == "running"

        cost = Decimal("0.0000147")
        await repository.finish_ok(
            run_id,
            output="hi",
            input_tokens=3,
            output_tokens=2,
            requests=1,
            cost=cost,
            latency_ms=12,
        )
        finished = await repository.get(run_id)
        assert finished is not None
        assert finished.status == "ok"
        assert finished.output == "hi"
        assert finished.input_tokens == 3
        assert finished.output_tokens == 2
        assert finished.requests == 1
        assert finished.cost == cost
        assert finished.latency_ms == 12

        failed_id = uuid4().hex
        await repository.create_running(
            failed_id,
            agent="assistant",
            manifest_digest="digest",
            input="fail",
        )
        await repository.finish_failed(failed_id, error="boom", latency_ms=5)
        failed = await repository.get(failed_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error == "boom"

        child_id = uuid4().hex
        await repository.create_running(
            child_id,
            agent="assistant",
            manifest_digest="digest",
            input="child",
            parent_id=run_id,
        )
        children = await repository.list_children(run_id)
        assert [child.id for child in children] == [child_id]

    asyncio.run(scenario())
