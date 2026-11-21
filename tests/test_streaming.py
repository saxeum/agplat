"""The SSE endpoint and the run span it leaves behind."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import PartDeltaEvent, TextPartDelta
from pydantic_ai.models.test import TestModel

from agplat import tracing
from agplat.agents.registry import AgentRegistry
from agplat.api.agents import _limits, _stream_run
from agplat.main import create_app
from agplat.settings import Settings
from tests.conftest import AGENTS_DIR, run_attributes, tool_calling_agent


class FailingStreamingAgent:
    @asynccontextmanager
    async def run_stream_events(self, *args: object, **kwargs: object) -> AsyncIterator[object]:
        raise RuntimeError("boom")
        yield  # pragma: no cover


class SlowStreamingAgent:
    @asynccontextmanager
    async def run_stream_events(self, *args: object, **kwargs: object) -> AsyncIterator[object]:
        async def events() -> AsyncIterator[PartDeltaEvent]:
            yield PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="hi"))
            await asyncio.sleep(3600)

        yield events()


class EmptyDeltaStreamingAgent:
    @asynccontextmanager
    async def run_stream_events(self, *args: object, **kwargs: object) -> AsyncIterator[object]:
        async def events() -> AsyncIterator[PartDeltaEvent]:
            yield PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=""))

        yield events()


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data_line = next(line for line in lines if line.startswith("data: "))
        data = json.loads(data_line.removeprefix("data: "))
        events.append((event, data))
    return events


def test_stream_emits_deltas_and_records_the_run(
    client: TestClient, spans: InMemorySpanExporter
) -> None:
    with client.stream(
        "POST",
        "/agents/assistant/runs/stream",
        json={"input": "say hi"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = parse_sse(body)
    names = [name for name, _ in events]
    assert names[0] == "run.started"
    assert "output.delta" in names
    assert names[-1] == "run.completed"

    completed = dict(events)["run.completed"]
    assert completed["run_id"]
    assert completed["output"]
    assert completed["usage"]["requests"] >= 1

    attrs = run_attributes(spans, completed["run_id"])
    assert attrs[tracing.STATUS] == "ok"
    assert attrs[tracing.OUTPUT] == completed["output"]


def test_stream_failure_emits_run_failed(client: TestClient, spans: InMemorySpanExporter) -> None:
    app = cast(FastAPI, client.app)
    loaded = app.state.registry.get("assistant")
    app.state.registry.agents["assistant"] = replace(
        loaded,
        agent=cast(Any, FailingStreamingAgent()),
    )

    with client.stream(
        "POST",
        "/agents/assistant/runs/stream",
        json={"input": "fail"},
    ) as response:
        body = "".join(response.iter_text())

    events = parse_sse(body)
    assert [name for name, _ in events] == ["run.started", "run.failed"]
    failed = dict(events)["run.failed"]
    assert failed["code"] == "run_failed"
    assert failed["detail"] == "boom"

    attrs = run_attributes(spans, failed["run_id"])
    assert attrs[tracing.STATUS] == "failed"
    assert attrs[tracing.ERROR] == "boom"


def test_stream_honours_the_request_limit(monkeypatch, spans: InMemorySpanExporter) -> None:
    monkeypatch.setenv("AGPLAT_REQUEST_LIMIT", "1")
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    app = create_app(settings=Settings(), registry=registry)
    app.state.registry.agents["assistant"] = replace(
        registry.get("assistant"),
        agent=tool_calling_agent(),
    )

    with (
        TestClient(app) as client,
        client.stream(
            "POST",
            "/agents/assistant/runs/stream",
            json={"input": "go"},
        ) as response,
    ):
        body = "".join(response.iter_text())

    events = parse_sse(body)
    names = [name for name, _ in events]
    assert names[0] == "run.started"
    assert names[-1] == "run.failed"
    assert "run.completed" not in names

    failed = dict(events)["run.failed"]
    assert "request_limit of 1" in failed["detail"]
    assert run_attributes(spans, failed["run_id"])[tracing.ERROR] == failed["detail"]


def test_stream_unknown_agent_is_404(client: TestClient) -> None:
    response = client.post("/agents/nope/runs/stream", json={"input": "hi"})

    assert response.status_code == 404
    assert response.json() == {
        "detail": "unknown agent: nope",
        "code": "unknown_agent",
        "run_id": None,
    }


def test_disconnect_records_the_run_as_failed(spans: InMemorySpanExporter) -> None:
    async def scenario() -> None:
        run_id = "disconnect-1"
        loaded = cast(Any, SimpleNamespace(agent=SlowStreamingAgent(), digest="digest"))

        stream = _stream_run(
            loaded=loaded,
            name="assistant",
            prompt="hi",
            run_id=run_id,
            limits=_limits(Settings()),
        )
        assert (await stream.__anext__()).startswith("event: run.started")
        assert (await stream.__anext__()).startswith("event: output.delta")
        await stream.aclose()

        attrs = run_attributes(spans, run_id)
        assert attrs[tracing.STATUS] == "failed"
        assert attrs[tracing.ERROR] == "client disconnected"

    asyncio.run(scenario())


def test_stream_without_a_result_fails_cleanly(spans: InMemorySpanExporter) -> None:
    async def scenario() -> None:
        run_id = "empty-1"
        loaded = cast(Any, SimpleNamespace(agent=EmptyDeltaStreamingAgent(), digest="digest"))

        stream = _stream_run(
            loaded=loaded,
            name="assistant",
            prompt="hi",
            run_id=run_id,
            limits=_limits(Settings()),
        )
        chunks = [chunk async for chunk in stream]

        names = [parse_sse(chunk)[0][0] for chunk in chunks]
        assert names == ["run.started", "run.failed"]
        attrs = run_attributes(spans, run_id)
        assert attrs[tracing.STATUS] == "failed"
        assert "without a result" in str(attrs[tracing.ERROR])

    asyncio.run(scenario())
