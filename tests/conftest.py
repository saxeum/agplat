"""Shared fixtures: TestModel registry, in-memory span store, no network."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agplat import tracing
from agplat.agents.registry import AgentRegistry
from agplat.deps import RunDeps
from agplat.main import create_app
from agplat.runs import StoredRun, stored_run_from_spans
from agplat.settings import Settings

AGENTS_DIR = Path(__file__).parent.parent / "agents"
PHOENIX_URL = "http://phoenix.test"


def span_dict(span: ReadableSpan) -> dict[str, Any]:
    """One captured span in Phoenix's JSON shape, so the same mapping is tested."""
    context = span.context
    assert context is not None  # a span always has a context once it exists
    start_ns = span.start_time or 0
    end_ns = span.end_time
    return {
        "name": span.name,
        "context": {
            "trace_id": format(context.trace_id, "032x"),
            "span_id": format(context.span_id, "016x"),
        },
        "parent_id": format(span.parent.span_id, "016x") if span.parent else None,
        "start_time": datetime.fromtimestamp(start_ns / 1e9, tz=UTC).isoformat(),
        "end_time": (datetime.fromtimestamp(end_ns / 1e9, tz=UTC).isoformat() if end_ns else None),
        "attributes": json.loads(json.dumps(dict(span.attributes or {}), default=str)),
    }


def run_attributes(exporter: InMemorySpanExporter, run_id: str) -> dict[str, Any]:
    """The attributes of the run span the app emitted for ``run_id``."""
    for finished in exporter.get_finished_spans():
        attrs = dict(finished.attributes or {})
        if attrs.get(tracing.RUN_ID) == run_id:
            return attrs
    raise AssertionError(f"no run span was emitted for {run_id}")


class InMemoryRunStore:
    """Reads the runs the app actually emitted, through the real mapping."""

    def __init__(self, exporter: InMemorySpanExporter) -> None:
        self._exporter = exporter

    async def get(self, run_id: str) -> StoredRun | None:
        spans = [span_dict(s) for s in self._exporter.get_finished_spans()]
        return stored_run_from_spans(spans, run_id)


class FakeRunStore:
    """A store with no history: every read is a 404."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def get(self, run_id: str) -> StoredRun | None:
        self.asked.append(run_id)
        return None


@pytest.fixture(scope="session")
def exporter() -> SpanExporter:
    """Install one in-memory provider for the whole session; tracing is global."""
    in_memory = InMemorySpanExporter()
    tracing.configure(Settings(phoenix_url=None), exporter=in_memory)
    return in_memory


@pytest.fixture
def spans(exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    exporter.clear()
    return exporter


def tool_calling_agent() -> Agent[RunDeps, str]:
    """An agent whose turn costs two model requests, so ``request_limit=1`` bites."""
    agent: Agent[RunDeps, str] = Agent(TestModel(), deps_type=RunDeps, instructions="call the tool")

    @agent.tool_plain
    def ping() -> str:
        return "pong"

    return agent


@pytest.fixture
def runs(spans: InMemorySpanExporter) -> InMemoryRunStore:
    return InMemoryRunStore(spans)


@pytest.fixture
def client(runs: InMemoryRunStore) -> Iterator[TestClient]:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    settings = Settings(phoenix_url=PHOENIX_URL)
    with TestClient(create_app(settings=settings, registry=registry, runs=runs)) as test_client:
        yield test_client
