"""The HTTP contract, exercised without a model or a database."""

from dataclasses import replace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fakes import FakeRunStore


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


def test_a_run_returns_text_and_usage(client: TestClient, runs: FakeRunStore) -> None:
    response = client.post("/agents/assistant/runs", json={"input": "say hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert isinstance(body["output"], str)
    assert body["output"]
    assert body["usage"]["requests"] >= 1

    digest = client.get("/agents/assistant").json()["digest"]
    assert runs.created == [
        {
            "run_id": body["run_id"],
            "agent": "assistant",
            "manifest_digest": digest,
            "input": "say hi",
            "parent_id": None,
        }
    ]
    assert len(runs.ok) == 1
    ok = runs.ok[0]
    assert ok["run_id"] == body["run_id"]
    assert ok["output"] == body["output"]
    assert ok["requests"] == body["usage"]["requests"]
    assert isinstance(ok["latency_ms"], int)


def test_a_failed_run_is_recorded(client: TestClient, runs: FakeRunStore) -> None:
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

    assert len(runs.created) == 1
    assert len(runs.failed) == 1
    assert runs.failed[0]["run_id"] == body["run_id"]
    assert runs.failed[0]["error"] == "boom"
    assert isinstance(runs.failed[0]["latency_ms"], int)
    assert runs.ok == []


def test_empty_input_is_rejected(client: TestClient) -> None:
    response = client.post("/agents/assistant/runs", json={"input": ""})

    assert response.status_code == 422


def test_a_run_failure_survives_a_record_failure(
    client: TestClient,
    runs: FakeRunStore,
    monkeypatch,
    caplog,
) -> None:
    app = cast(FastAPI, client.app)
    loaded = app.state.registry.get("assistant")
    app.state.registry.agents["assistant"] = replace(
        loaded,
        agent=cast(Any, FailingAgent()),
    )

    async def broken_finish(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(runs, "finish_failed", broken_finish)

    response = client.post("/agents/assistant/runs", json={"input": "fail"})

    assert response.status_code == 500
    assert response.json()["code"] == "run_failed"
    assert "could not record failed run" in caplog.text
