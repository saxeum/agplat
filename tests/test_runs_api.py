"""Reading a persisted run over HTTP."""

import asyncio

from fastapi.testclient import TestClient

from tests.fakes import FakeRunStore


def test_get_run_returns_the_completed_row(
    client: TestClient,
    runs: FakeRunStore,
) -> None:
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


def test_get_run_does_not_run_the_agent(
    client: TestClient,
    runs: FakeRunStore,
) -> None:
    posted = client.post("/agents/assistant/runs", json={"input": "say hi"}).json()
    before = len(runs.created)

    client.get(f"/runs/{posted['run_id']}")

    assert len(runs.created) == before


def test_get_run_includes_children(
    client: TestClient,
    runs: FakeRunStore,
) -> None:
    posted = client.post("/agents/assistant/runs", json={"input": "parent"}).json()
    child_id = "child-1"
    asyncio.run(
        runs.create_running(
            child_id,
            agent="assistant",
            manifest_digest="child-digest",
            input="child",
            parent_id=posted["run_id"],
        )
    )

    response = client.get(f"/runs/{posted['run_id']}")

    assert response.status_code == 200
    assert [child["run_id"] for child in response.json()["children"]] == [child_id]


def test_unknown_run_is_404(client: TestClient) -> None:
    response = client.get("/runs/nope")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "unknown run: nope",
        "code": "run_not_found",
        "run_id": None,
    }
