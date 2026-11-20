"""Run records: one row per request, written before and after the model call."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

import asyncpg

RUN_COLUMNS = (
    "id, parent_id, agent, manifest_digest, input, output, status, error, "
    "input_tokens, output_tokens, requests, cost, latency_ms, created_at"
)


@dataclass(frozen=True)
class Run:
    """The row shape from DESIGN.md §14."""

    id: str
    parent_id: str | None
    agent: str
    manifest_digest: str
    input: str
    output: str | None
    status: str
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    requests: int | None
    cost: Decimal | None
    latency_ms: int | None
    created_at: datetime


class RunStore(Protocol):
    """What the run endpoint needs. Tests provide a fake of this."""

    async def create_running(
        self,
        run_id: str,
        *,
        agent: str,
        manifest_digest: str,
        input: str,
        parent_id: str | None = None,
    ) -> None: ...

    async def finish_ok(
        self,
        run_id: str,
        *,
        output: str,
        input_tokens: int,
        output_tokens: int,
        requests: int,
        cost: Decimal | None,
        latency_ms: int,
    ) -> None: ...

    async def finish_failed(self, run_id: str, *, error: str, latency_ms: int) -> None: ...

    async def get(self, run_id: str) -> "Run | None": ...

    async def list_children(self, parent_id: str) -> list["Run"]: ...


class RunRepository:
    """All SQL for runs lives here; routes never see a query."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[asyncpg.Connection]:
        connection = await asyncpg.connect(self._dsn)
        try:
            yield connection
        finally:
            await connection.close()

    async def create_running(
        self,
        run_id: str,
        *,
        agent: str,
        manifest_digest: str,
        input: str,
        parent_id: str | None = None,
    ) -> None:
        async with self._connection() as connection:
            await connection.execute(
                """
                insert into runs (id, parent_id, agent, manifest_digest, input, status)
                values ($1, $2, $3, $4, $5, 'running')
                """,
                run_id,
                parent_id,
                agent,
                manifest_digest,
                input,
            )

    async def finish_ok(
        self,
        run_id: str,
        *,
        output: str,
        input_tokens: int,
        output_tokens: int,
        requests: int,
        cost: Decimal | None,
        latency_ms: int,
    ) -> None:
        async with self._connection() as connection:
            await connection.execute(
                """
                update runs
                set status = 'ok',
                    output = $2,
                    input_tokens = $3,
                    output_tokens = $4,
                    requests = $5,
                    cost = $6,
                    latency_ms = $7,
                    error = null
                where id = $1
                """,
                run_id,
                output,
                input_tokens,
                output_tokens,
                requests,
                cost,
                latency_ms,
            )

    async def finish_failed(self, run_id: str, *, error: str, latency_ms: int) -> None:
        async with self._connection() as connection:
            await connection.execute(
                """
                update runs
                set status = 'failed', error = $2, latency_ms = $3
                where id = $1
                """,
                run_id,
                error,
                latency_ms,
            )

    async def get(self, run_id: str) -> Run | None:
        async with self._connection() as connection:
            row = await connection.fetchrow(
                f"select {RUN_COLUMNS} from runs where id = $1",
                run_id,
            )
        return _to_run(row) if row is not None else None

    async def list_children(self, parent_id: str) -> list[Run]:
        async with self._connection() as connection:
            rows = await connection.fetch(
                f"select {RUN_COLUMNS} from runs where parent_id = $1 order by created_at",
                parent_id,
            )
        return [_to_run(row) for row in rows]


def _to_run(row: Any) -> Run:
    return Run(**dict(row))
