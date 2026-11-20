"""The HTTP contract, exercised without a model or a database."""

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_lists_the_assistant(client: TestClient) -> None:
    response = client.get("/agents")

    assert response.status_code == 200
    names = {agent["name"] for agent in response.json()}
    assert "assistant" in names


def test_agent_detail_exposes_the_digest(client: TestClient) -> None:
    body = client.get("/agents/assistant").json()

    assert body["digest"]
    assert body["description"]


def test_unknown_agent_is_404(client: TestClient) -> None:
    assert client.get("/agents/nope").status_code == 404
    assert client.post("/agents/nope/runs", json={"input": "hi"}).status_code == 404


def test_a_run_returns_text_and_usage(client: TestClient) -> None:
    response = client.post("/agents/assistant/runs", json={"input": "say hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert isinstance(body["output"], str)
    assert body["output"]
    assert body["usage"]["requests"] >= 1


def test_empty_input_is_rejected(client: TestClient) -> None:
    response = client.post("/agents/assistant/runs", json={"input": ""})

    assert response.status_code == 422
