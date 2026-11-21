"""Test doubles shared across the HTTP and repository tests."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from agplat.runs import Run


class FakeRunStore:
    """An in-memory run store that records what the endpoint asked it to do."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.ok: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.runs: dict[str, Run] = {}

    async def create_running(
        self,
        run_id: str,
        *,
        agent: str,
        manifest_digest: str,
        input: str,
        parent_id: str | None = None,
    ) -> None:
        self.created.append(
            {
                "run_id": run_id,
                "agent": agent,
                "manifest_digest": manifest_digest,
                "input": input,
                "parent_id": parent_id,
            }
        )
        self.runs[run_id] = Run(
            id=run_id,
            parent_id=parent_id,
            agent=agent,
            manifest_digest=manifest_digest,
            input=input,
            output=None,
            status="running",
            error=None,
            input_tokens=None,
            output_tokens=None,
            requests=None,
            cost=None,
            latency_ms=None,
            created_at=datetime.now(tz=UTC),
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
        self.ok.append(
            {
                "run_id": run_id,
                "output": output,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "requests": requests,
                "cost": cost,
                "latency_ms": latency_ms,
            }
        )
        self.runs[run_id] = replace(
            self.runs[run_id],
            status="ok",
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requests=requests,
            cost=cost,
            latency_ms=latency_ms,
        )

    async def finish_failed(self, run_id: str, *, error: str, latency_ms: int) -> None:
        self.failed.append({"run_id": run_id, "error": error, "latency_ms": latency_ms})
        self.runs[run_id] = replace(
            self.runs[run_id],
            status="failed",
            error=error,
            latency_ms=latency_ms,
        )

    async def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    async def list_children(self, parent_id: str) -> list[Run]:
        return [run for run in self.runs.values() if run.parent_id == parent_id]
