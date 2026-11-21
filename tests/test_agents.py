"""The HTTP contract, exercised without a model, a database or a network."""

from dataclasses import replace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.models.test import TestModel

from agplat import tracing
from agplat.agents.registry import AgentRegistry
from agplat.main import create_app
from agplat.settings import Settings
from tests.conftest import AGENTS_DIR, run_attributes, tool_calling_agent


class FailingAgent:
    async def run(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("boom")


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_lists_the_assistant(client: TestClient) -> None:
    response = client.get("/agents")

    assert response.status_code == 200
    names = {agent["name"] for agent in response.json()}
    assert "assistant" in names


def test_agent_detail_exposes_the_digest(client: TestClient) -> None:
    body = client.get("/agents/assistant").json()

    assert set(body) == {"name", "description", "model", "digest"}
    assert body["model"] == "deepseek:deepseek-flash"
    assert body["digest"]
    assert body["description"]


def test_unknown_agent_is_404(client: TestClient) -> None:
    assert client.get("/agents/nope").status_code == 404

    response = client.post("/agents/nope/runs", json={"input": "hi"})

    assert response.status_code == 404
    assert response.json() == {
        "detail": "unknown agent: nope",
        "code": "unknown_agent",
        "run_id": None,
    }


def test_a_run_returns_text_and_usage(client: TestClient, spans: InMemorySpanExporter) -> None:
    response = client.post("/agents/assistant/runs", json={"input": "say hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert isinstance(body["output"], str)
    assert body["output"]
    assert body["usage"]["requests"] >= 1


def test_a_successful_run_span_carries_the_record(
    client: TestClient, spans: InMemorySpanExporter
) -> None:
    body = client.post("/agents/assistant/runs", json={"input": "say hi"}).json()

    attrs = run_attributes(spans, body["run_id"])

    assert attrs[tracing.STATUS] == "ok"
    assert attrs[tracing.AGENT] == "assistant"
    assert attrs[tracing.INPUT] == "say hi"
    assert attrs[tracing.OUTPUT] == body["output"]
    assert attrs[tracing.REQUESTS] == body["usage"]["requests"]
    assert attrs[tracing.DIGEST] == client.get("/agents/assistant").json()["digest"]
    assert isinstance(attrs[tracing.LATENCY_MS], int)


def test_a_failed_run_span_says_why(client: TestClient, spans: InMemorySpanExporter) -> None:
    app = cast(FastAPI, client.app)
    loaded = app.state.registry.get("assistant")
    app.state.registry.agents["assistant"] = replace(
        loaded,
        agent=cast(Any, FailingAgent()),
    )

    response = client.post("/agents/assistant/runs", json={"input": "fail"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "run_failed"
    assert body["detail"] == "boom"
    assert body["run_id"]

    attrs = run_attributes(spans, body["run_id"])
    assert attrs[tracing.STATUS] == "failed"
    assert attrs[tracing.ERROR] == "boom"
    assert isinstance(attrs[tracing.LATENCY_MS], int)


def test_request_limit_defaults_to_four(monkeypatch) -> None:
    monkeypatch.delenv("AGPLAT_REQUEST_LIMIT", raising=False)

    assert Settings().request_limit == 4


def test_request_limit_comes_from_the_environment(monkeypatch, spans: InMemorySpanExporter) -> None:
    monkeypatch.setenv("AGPLAT_REQUEST_LIMIT", "1")
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    app = create_app(settings=Settings(), registry=registry)
    app.state.registry.agents["assistant"] = replace(
        registry.get("assistant"),
        agent=tool_calling_agent(),
    )

    with TestClient(app) as client:
        response = client.post("/agents/assistant/runs", json={"input": "go"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "run_failed"
    assert "request_limit of 1" in body["detail"]

    attrs = run_attributes(spans, body["run_id"])
    assert attrs[tracing.STATUS] == "failed"
    assert attrs[tracing.ERROR] == body["detail"]


def test_empty_input_is_rejected(client: TestClient) -> None:
    response = client.post("/agents/assistant/runs", json={"input": ""})

    assert response.status_code == 422


def test_health_probes_are_not_traced(client: TestClient, spans: InMemorySpanExporter) -> None:
    for _ in range(3):
        client.get("/health")

    assert [s.name for s in spans.get_finished_spans()] == []
