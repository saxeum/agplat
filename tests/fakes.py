"""Test doubles shared across the HTTP and repository tests."""

from decimal import Decimal
from typing import Any


class FakeRunStore:
    """Records what the run endpoint asked the repository to do."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.ok: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

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

    async def finish_failed(self, run_id: str, *, error: str, latency_ms: int) -> None:
        self.failed.append(
            {"run_id": run_id, "error": error, "latency_ms": latency_ms}
        )
