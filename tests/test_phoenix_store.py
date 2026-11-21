"""Phoenix's HTTP shape, and the span-to-run mapping, without a server."""

import asyncio
from typing import Any

import httpx
import pytest

from agplat import tracing
from agplat.runs import PhoenixStore, PhoenixUnavailable, stored_run_from_spans

ROOT_ID = "a" * 16
CHILD_ID = "b" * 16


def span(
    *,
    span_id: str = ROOT_ID,
    parent_id: str | None = None,
    run_id: str | None = "run-1",
    **extra: Any,
) -> dict[str, Any]:
    def key(name: str) -> str:
        return name if name.startswith("agplat.") else f"agplat.{name}"

    attributes: dict[str, Any] = {
        tracing.RUN_ID: run_id,
        tracing.AGENT: "assistant",
        tracing.DIGEST: "digest",
        tracing.INPUT: "hi",
        tracing.STATUS: "ok",
        tracing.INPUT_TOKENS: 3,
        tracing.OUTPUT_TOKENS: 2,
        tracing.REQUESTS: 1,
        tracing.COST: "0.0000147",
        tracing.LATENCY_MS: 12,
        **{key(k): v for k, v in extra.items()},
    }
    return {
        "context": {"trace_id": "f" * 32, "span_id": span_id},
        "parent_id": parent_id,
        "start_time": "2026-11-21T10:00:00+00:00",
        "end_time": "2026-11-21T10:00:00.250000+00:00",
        "attributes": attributes,
    }


def test_a_run_is_mapped_from_its_span() -> None:
    stored = stored_run_from_spans([span(output="done")], "run-1")

    assert stored is not None
    assert stored.run.id == "run-1"
    assert stored.run.status == "ok"
    assert stored.run.output == "done"
    assert stored.run.requests == 1
    assert str(stored.run.cost) == "0.0000147"
    assert stored.run.latency_ms == 12
    assert stored.children == []


def test_child_runs_are_spans_that_carry_a_run_id() -> None:
    child = span(span_id=CHILD_ID, parent_id=ROOT_ID, run_id="child-1")
    model_span = span(span_id="c" * 16, parent_id=ROOT_ID, run_id=None)

    stored = stored_run_from_spans([span(), child, model_span], "run-1")

    assert stored is not None
    assert [c.id for c in stored.children] == ["child-1"]
    assert stored.children[0].parent_id == "run-1"


def test_latency_falls_back_to_the_span_timestamps() -> None:
    timed = span()
    del timed["attributes"][tracing.LATENCY_MS]

    stored = stored_run_from_spans([timed], "run-1")

    assert stored is not None
    assert stored.run.latency_ms == 250


def test_absent_fields_do_not_crash_the_mapping() -> None:
    bare = span()
    del bare["attributes"][tracing.COST]
    bare["attributes"][tracing.PARENT_ID] = None

    stored = stored_run_from_spans([bare], "run-1")

    assert stored is not None
    assert stored.run.cost is None
    assert stored.run.output is None
    assert stored.run.parent_id is None


def test_unparseable_cost_is_dropped_rather_than_crashing() -> None:
    stored = stored_run_from_spans([span(**{tracing.COST: "not a decimal"})], "run-1")

    assert stored is not None
    assert stored.run.cost is None


def test_a_missing_run_is_none() -> None:
    assert stored_run_from_spans([span(run_id="other")], "run-1") is None


def test_the_store_finds_the_run_by_attribute_then_reads_its_trace() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [span(parent_id=None)], "next_cursor": None})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = PhoenixStore("http://phoenix.test/", project="agplat", client=client)

    stored = asyncio.run(store.get("run-1"))

    assert stored is not None
    assert stored.run.id == "run-1"
    assert len(seen) == 2
    assert all(str(r.url).startswith("http://phoenix.test/v1/projects/agplat/spans") for r in seen)
    assert seen[0].url.params["attribute"] == f"{tracing.RUN_ID}:run-1"
    assert seen[1].url.params["trace_id"] == "f" * 32


def test_the_store_sends_the_api_key_when_it_has_one() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = PhoenixStore("http://phoenix.test", api_key="secret", client=client)

    assert asyncio.run(store.get("absent")) is None
    assert seen[0].headers["authorization"] == "Bearer secret"


def test_an_empty_result_is_a_missing_run() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
    )

    assert asyncio.run(PhoenixStore("http://p", client=client).get("nope")) is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_a_bad_answer_is_unavailable(response: httpx.Response) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response))

    with pytest.raises(PhoenixUnavailable):
        asyncio.run(PhoenixStore("http://p", client=client).get("run-1"))


def test_a_transport_error_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(PhoenixUnavailable):
        asyncio.run(PhoenixStore("http://p", client=client).get("run-1"))


def test_a_span_without_an_end_time_has_no_latency() -> None:
    open_span = span()
    del open_span["attributes"][tracing.LATENCY_MS]
    open_span["end_time"] = None

    stored = stored_run_from_spans([open_span], "run-1")

    assert stored is not None
    assert stored.run.latency_ms is None


def test_a_run_that_appears_after_a_retry_is_returned() -> None:
    answers = [[], [span(parent_id=None)], [span(parent_id=None)]]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": answers.pop(0) if answers else []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = PhoenixStore("http://p", client=client, retry_delay=0)

    stored = asyncio.run(store.get("run-1"))

    assert stored is not None
    assert stored.run.id == "run-1"


def test_a_run_that_never_appears_is_unknown_after_the_retries() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = PhoenixStore("http://p", client=client, retry_delay=0)

    assert asyncio.run(store.get("absent")) is None
    assert len(calls) == 3
