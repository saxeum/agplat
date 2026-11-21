"""The SSE endpoint and its run-row lifecycle."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai import PartDeltaEvent, TextPartDelta
from pydantic_ai.models.test import TestModel

from agplat.agents.registry import AgentRegistry
from agplat.api.agents import _limits, _record_failure, _stream_run
from agplat.main import create_app
from agplat.settings import Settings
from tests.conftest import AGENTS_DIR, tool_calling_agent
from tests.fakes import FakeRunStore


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


class CancelledFinishStore(FakeRunStore):
    async def finish_failed(self, run_id: str, *, error: str, latency_ms: int) -> None:
        raise asyncio.CancelledError


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data_line = next(line for line in lines if line.startswith("data: "))
        data = json.loads(data_line.removeprefix("data: "))
        events.append((event, data))
    return events


def test_stream_emits_deltas_and_persists(client: TestClient, runs: FakeRunStore) -> None:
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

    assert runs.ok[0]["run_id"] == completed["run_id"]


def test_stream_failure_emits_run_failed(client: TestClient, runs: FakeRunStore) -> None:
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
    assert runs.failed[0]["run_id"] == failed["run_id"]


def test_stream_honours_the_request_limit(
    monkeypatch, runs: FakeRunStore
) -> None:
    monkeypatch.setenv("AGPLAT_REQUEST_LIMIT", "1")
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    app = create_app(settings=Settings(), registry=registry, runs=runs)
    app.state.registry.agents["assistant"] = replace(
        registry.get("assistant"),
        agent=tool_calling_agent(),
    )

    with TestClient(app) as client, client.stream(
        "POST",
        "/agents/assistant/runs/stream",
        json={"input": "go"},
    ) as response:
        body = "".join(response.iter_text())

    events = parse_sse(body)
    names = [name for name, _ in events]
    assert names[0] == "run.started"
    assert names[-1] == "run.failed"
    assert "run.completed" not in names

    failed = dict(events)["run.failed"]
    assert "request_limit of 1" in failed["detail"]
    assert runs.failed[0]["error"] == failed["detail"]


def test_stream_unknown_agent_is_404(client: TestClient) -> None:
    response = client.post("/agents/nope/runs/stream", json={"input": "hi"})

    assert response.status_code == 404
    assert response.json() == {
        "detail": "unknown agent: nope",
        "code": "unknown_agent",
        "run_id": None,
    }


def test_disconnect_marks_the_run_failed() -> None:
    async def scenario() -> None:
        store = FakeRunStore()
        run_id = "disconnect-1"
        await store.create_running(
            run_id,
            agent="assistant",
            manifest_digest="digest",
            input="hi",
        )
        loaded = cast(Any, SimpleNamespace(agent=SlowStreamingAgent()))

        stream = _stream_run(
            loaded=loaded,
            name="assistant",
            prompt="hi",
            run_id=run_id,
            runs=store,
            limits=_limits(Settings()),
        )
        assert (await stream.__anext__()).startswith("event: run.started")
        assert (await stream.__anext__()).startswith("event: output.delta")
        await stream.aclose()

        assert store.failed[0]["run_id"] == run_id
        assert store.failed[0]["error"] == "client disconnected"

    asyncio.run(scenario())


def test_stream_without_a_result_fails_cleanly() -> None:
    async def scenario() -> None:
        store = FakeRunStore()
        run_id = "empty-1"
        await store.create_running(
            run_id,
            agent="assistant",
            manifest_digest="digest",
            input="hi",
        )
        loaded = cast(Any, SimpleNamespace(agent=EmptyDeltaStreamingAgent()))

        stream = _stream_run(
            loaded=loaded,
            name="assistant",
            prompt="hi",
            run_id=run_id,
            runs=store,
            limits=_limits(Settings()),
        )
        chunks = [chunk async for chunk in stream]

        names = [parse_sse(chunk)[0][0] for chunk in chunks]
        assert names == ["run.started", "run.failed"]
        assert store.failed[0]["run_id"] == run_id

    asyncio.run(scenario())


def test_record_failure_propagates_cancellation() -> None:
    async def scenario() -> None:
        with pytest.raises(asyncio.CancelledError):
            await _record_failure(CancelledFinishStore(), "run-1", "boom", 1)

    asyncio.run(scenario())
