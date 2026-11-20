"""Integration tests: host pytest against the compose Postgres."""

import asyncio
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from agplat.agents.registry import AgentRegistry
from agplat.main import create_app
from agplat.runs import Run, RunRepository
from agplat.settings import Settings

pytestmark = pytest.mark.integration

AGENTS_DIR = Path(__file__).parent.parent / "agents"


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


def test_route_persists_a_run(db_url: str) -> None:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    app = create_app(
        settings=Settings(db_url=db_url, agents_dir=AGENTS_DIR),
        registry=registry,
        runs=RunRepository(db_url),
    )

    with TestClient(app) as client:
        response = client.post("/agents/assistant/runs", json={"input": "hi"})

    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]

    async def read() -> Run | None:
        return await RunRepository(db_url).get(run_id)

    run = asyncio.run(read())
    assert run is not None
    assert run.status == "ok"
    assert run.agent == "assistant"
    assert run.output == body["output"]
    assert run.manifest_digest == registry.get("assistant").digest
    assert run.requests == body["usage"]["requests"]
