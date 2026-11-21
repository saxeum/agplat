"""Reading runs back out of the trace store.

There is no write path here: spans are emitted by the routes and shipped by the
tracer. This module is the read side — it turns Phoenix's span JSON into the row
the API promises, and it is the only thing that knows Phoenix's HTTP shape.
"""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from agplat import tracing


class PhoenixUnavailable(Exception):
    """The trace store could not be reached or answered badly."""


@dataclass(frozen=True)
class Run:
    """One run, as the API returns it."""

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


@dataclass(frozen=True)
class StoredRun:
    """A run and its direct children, read in one pass."""

    run: Run
    children: list[Run]


class RunStore(Protocol):
    """What the read endpoint needs. Tests provide a fake of this."""

    async def get(self, run_id: str) -> StoredRun | None: ...


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    return span.get("attributes") or {}


def _seconds_between(span: dict[str, Any]) -> int | None:
    start, end = span.get("start_time"), span.get("end_time")
    if not start or not end:
        return None
    return int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)


def _to_run(span: dict[str, Any]) -> Run:
    attrs = _attrs(span)
    cost = attrs.get(tracing.COST)
    try:
        parsed_cost = Decimal(cost) if cost is not None else None
    except InvalidOperation:
        parsed_cost = None
    latency = attrs.get(tracing.LATENCY_MS)
    return Run(
        id=str(attrs.get(tracing.RUN_ID, "")),
        parent_id=attrs.get(tracing.PARENT_ID),
        agent=str(attrs.get(tracing.AGENT, "")),
        manifest_digest=str(attrs.get(tracing.DIGEST, "")),
        input=str(attrs.get(tracing.INPUT, "")),
        output=attrs.get(tracing.OUTPUT),
        status=str(attrs.get(tracing.STATUS, "unknown")),
        error=attrs.get(tracing.ERROR),
        input_tokens=attrs.get(tracing.INPUT_TOKENS),
        output_tokens=attrs.get(tracing.OUTPUT_TOKENS),
        requests=attrs.get(tracing.REQUESTS),
        cost=parsed_cost,
        latency_ms=int(latency) if latency is not None else _seconds_between(span),
        created_at=datetime.fromisoformat(span["start_time"]),
    )


def stored_run_from_spans(spans: list[dict[str, Any]], run_id: str) -> StoredRun | None:
    """Pick the run span out of a trace and collect its child runs.

    Only spans that carry ``agplat.run_id`` are runs: a model or tool span is
    part of a run, not a run of its own.
    """
    root = next((s for s in spans if _attrs(s).get(tracing.RUN_ID) == run_id), None)
    if root is None:
        return None
    run = _to_run(root)
    root_span_id = (root.get("context") or {}).get("span_id")
    children: list[Run] = []
    for span in spans:
        if span is root or span.get("parent_id") != root_span_id:
            continue
        if _attrs(span).get(tracing.RUN_ID) in (None, run_id):
            continue
        child = _to_run(span)
        children.append(replace(child, parent_id=child.parent_id or run.id))
    return StoredRun(run=run, children=children)


class PhoenixStore:
    """``GET /runs/{id}`` over Phoenix's REST API.

    One request finds the run span by attribute; a second pulls the whole trace
    so children come from the same read. Phoenix is a runtime dependency of this
    endpoint and of nothing else.
    """

    def __init__(
        self,
        base_url: str,
        project: str = "default",
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 2.0,
        retries: int = 3,
        retry_delay: float = 0.05,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._project = project
        self._spans_path = f"/v1/projects/{quote(project)}/spans"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._retries = retries
        self._retry_delay = retry_delay

    async def _spans(self, **params: Any) -> list[dict[str, Any]]:
        try:
            response = await self._client.get(
                f"{self._base}{self._spans_path}", params=params, headers=self._headers
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PhoenixUnavailable(f"trace store unavailable: {exc}") from exc
        spans = payload.get("data")
        if not isinstance(spans, list):
            raise PhoenixUnavailable("trace store returned no span list")
        return spans

    async def get(self, run_id: str) -> StoredRun | None:
        # Phoenix acks a span, then writes it: a run read milliseconds after it
        # finished is briefly absent. Retry a little before calling it unknown.
        for attempt in range(self._retries):
            matched = await self._spans(attribute=f"{tracing.RUN_ID}:{run_id}", limit=1)
            if matched:
                break
            if attempt < self._retries - 1:
                await asyncio.sleep(self._retry_delay * (attempt + 1))
        else:
            return None
        trace_id = (matched[0].get("context") or {}).get("trace_id")
        spans = await self._spans(trace_id=trace_id, limit=200) if trace_id else matched
        return stored_run_from_spans(spans, run_id)
