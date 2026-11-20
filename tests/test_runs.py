"""The run repository, exercised with a fake connection."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import asyncpg

from agplat.runs import Run, RunRepository


class FakeConnection:
    def __init__(
        self,
        *,
        row: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.row = row
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    async def execute(self, sql: str, *args: object) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def fetchrow(self, sql: str, *args: object) -> dict[str, Any] | None:
        self.executed.append((sql, args))
        return self.row

    async def fetch(self, sql: str, *args: object) -> list[dict[str, Any]]:
        self.executed.append((sql, args))
        return self.rows

    async def close(self) -> None:
        self.closed = True


def install(monkeypatch, connection: FakeConnection) -> None:
    async def fake_connect(dsn: str) -> FakeConnection:
        assert dsn == "postgresql://example"
        return connection

    monkeypatch.setattr(asyncpg, "connect", fake_connect)


def make_row(**overrides: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "run-1",
        "parent_id": None,
        "agent": "assistant",
        "manifest_digest": "digest",
        "input": "hello",
        "output": None,
        "status": "running",
        "error": None,
        "input_tokens": None,
        "output_tokens": None,
        "requests": None,
        "cost": None,
        "latency_ms": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    row.update(overrides)
    return row


def test_create_running_inserts_the_row(monkeypatch) -> None:
    connection = FakeConnection()
    install(monkeypatch, connection)

    asyncio.run(
        RunRepository("postgresql://example").create_running(
            "run-1",
            agent="assistant",
            manifest_digest="digest",
            input="hello",
        )
    )

    sql, args = connection.executed[0]
    assert "insert into runs" in sql
    assert args == ("run-1", None, "assistant", "digest", "hello")
    assert connection.closed


def test_finish_ok_updates_usage_and_latency(monkeypatch) -> None:
    connection = FakeConnection()
    install(monkeypatch, connection)
    cost = Decimal("0.0000147")

    asyncio.run(
        RunRepository("postgresql://example").finish_ok(
            "run-1",
            output="hi",
            input_tokens=3,
            output_tokens=2,
            requests=1,
            cost=cost,
            latency_ms=12,
        )
    )

    sql, args = connection.executed[0]
    assert "status = 'ok'" in sql
    assert args == ("run-1", "hi", 3, 2, 1, cost, 12)


def test_finish_failed_records_the_error(monkeypatch) -> None:
    connection = FakeConnection()
    install(monkeypatch, connection)

    asyncio.run(
        RunRepository("postgresql://example").finish_failed(
            "run-1",
            error="boom",
            latency_ms=5,
        )
    )

    sql, args = connection.executed[0]
    assert "status = 'failed'" in sql
    assert args == ("run-1", "boom", 5)


def test_get_returns_a_run(monkeypatch) -> None:
    row = make_row()
    connection = FakeConnection(row=row)
    install(monkeypatch, connection)

    run = asyncio.run(RunRepository("postgresql://example").get("run-1"))

    assert run == Run(**row)


def test_get_returns_none_when_missing(monkeypatch) -> None:
    connection = FakeConnection()
    install(monkeypatch, connection)

    assert asyncio.run(RunRepository("postgresql://example").get("nope")) is None


def test_list_children_returns_rows(monkeypatch) -> None:
    connection = FakeConnection(
        rows=[
            make_row(id="child-1", parent_id="run-1"),
            make_row(id="child-2", parent_id="run-1"),
        ]
    )
    install(monkeypatch, connection)

    children = asyncio.run(RunRepository("postgresql://example").list_children("run-1"))

    assert [child.id for child in children] == ["child-1", "child-2"]
