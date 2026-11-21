"""Reading a stored run over HTTP."""

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.models.test import TestModel

from agplat.agents.registry import AgentRegistry
from agplat.main import create_app
from agplat.runs import PhoenixStore, PhoenixUnavailable, Run, StoredRun
from agplat.settings import Settings, get_settings
from tests.conftest import AGENTS_DIR


class DownStore:
    async def get(self, run_id: str) -> None:
        raise PhoenixUnavailable("trace store unavailable: boom")


def test_get_run_returns_the_emitted_run(client: TestClient) -> None:
    posted = client.post("/agents/assistant/runs", json={"input": "say hi"}).json()

    response = client.get(f"/runs/{posted['run_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == posted["run_id"]
    assert body["agent"] == "assistant"
    assert body["status"] == "ok"
    assert body["input"] == "say hi"
    assert body["output"] == posted["output"]
    assert body["manifest_digest"]
    assert body["usage"]["requests"] == posted["usage"]["requests"]
    assert body["children"] == []
    assert isinstance(body["latency_ms"], int)
    assert body["created_at"]


def test_a_streamed_run_is_readable_too(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/agents/assistant/runs/stream",
        json={"input": "say hi"},
    ) as response:
        body = "".join(response.iter_text())

    completed = next(
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ") and '"usage"' in line
    )

    assert client.get(f"/runs/{completed['run_id']}").status_code == 200


def test_get_run_does_not_run_the_agent(client: TestClient, spans: InMemorySpanExporter) -> None:
    posted = client.post("/agents/assistant/runs", json={"input": "say hi"}).json()
    before = len([s for s in spans.get_finished_spans() if s.name == "run"])

    client.get(f"/runs/{posted['run_id']}")

    after = len([s for s in spans.get_finished_spans() if s.name == "run"])
    assert after == before


def test_unknown_run_is_404(client: TestClient) -> None:
    response = client.get("/runs/nope")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "unknown run: nope",
        "code": "run_not_found",
        "run_id": None,
    }


def test_read_is_503_when_tracing_is_disabled() -> None:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())

    with TestClient(create_app(settings=Settings(), registry=registry)) as client:
        response = client.get("/runs/anything")

    assert response.status_code == 503
    assert response.json()["code"] == "tracing_disabled"


def test_read_is_503_when_the_store_is_down() -> None:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    app = create_app(settings=Settings(), registry=registry, runs=DownStore())

    with TestClient(app) as client:
        response = client.get("/runs/anything")

    assert response.status_code == 503
    assert response.json()["code"] == "tracing_unavailable"
    assert "boom" in response.json()["detail"]


class FailedRunStore:
    def __init__(self) -> None:
        self.stored = StoredRun(
            run=Run(
                id="failed-1",
                parent_id=None,
                agent="assistant",
                manifest_digest="digest",
                input="hi",
                output=None,
                status="failed",
                error="boom",
                input_tokens=None,
                output_tokens=None,
                requests=None,
                cost=None,
                latency_ms=3,
                created_at=datetime(2026, 11, 21, tzinfo=UTC),
            ),
            children=[],
        )

    async def get(self, run_id: str) -> StoredRun | None:
        return self.stored if run_id == "failed-1" else None


def test_a_failed_run_is_returned_without_usage() -> None:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    app = create_app(settings=Settings(), registry=registry, runs=FailedRunStore())

    with TestClient(app) as client:
        body = client.get("/runs/failed-1").json()

    assert body["status"] == "failed"
    assert body["error"] == "boom"
    assert body["usage"] is None
    assert body["output"] is None


def test_a_configured_store_is_built_from_the_url() -> None:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())

    app = create_app(settings=Settings(phoenix_url="http://phoenix.test"), registry=registry)

    assert isinstance(app.state.runs, PhoenixStore)
    assert app.state.runs._base == "http://phoenix.test"


def test_no_url_means_no_store() -> None:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())

    assert create_app(settings=Settings(), registry=registry).state.runs is None


def test_settings_are_loaded_once(monkeypatch) -> None:
    monkeypatch.delenv("AGPLAT_REQUEST_LIMIT", raising=False)
    get_settings.cache_clear()

    assert get_settings() is get_settings()
    assert get_settings().request_limit == 4
    get_settings.cache_clear()
