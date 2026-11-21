"""The tracer glue: one provider per process, span attributes, a real flush."""

from typing import Any, cast

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agplat import tracing
from agplat.settings import Settings


def test_configure_installs_one_provider(spans: InMemorySpanExporter) -> None:
    before = tracing._provider

    tracing.configure(Settings(phoenix_url=None), exporter=InMemorySpanExporter())

    assert tracing._provider is before
    assert tracing.tracer() is not None


def test_flush_without_a_provider_is_a_no_op(monkeypatch) -> None:
    monkeypatch.setattr(tracing, "_provider", None)

    assert tracing.flush() is True


def test_flush_with_a_provider_flushes(spans: InMemorySpanExporter) -> None:
    with tracing.run_span(**{tracing.RUN_ID: "flush-1"}):
        pass

    assert tracing.flush() is True
    finished = spans.get_finished_spans()
    assert [cast(Any, s).attributes[tracing.RUN_ID] for s in finished] == ["flush-1"]


def test_a_run_span_starts_running_and_ends_with_a_state(
    spans: InMemorySpanExporter,
) -> None:
    with tracing.run_span(**{tracing.RUN_ID: "state-1", tracing.AGENT: "assistant"}) as span:
        assert cast(Any, span).attributes[tracing.STATUS] == "running"
        tracing.finish_span(
            span,
            latency_ms=7,
            **{tracing.STATUS: "ok", tracing.OUTPUT: "hi", tracing.REQUESTS: 1},
        )
    tracing.flush()

    finished = spans.get_finished_spans()
    assert finished
    attrs = dict(finished[0].attributes or {})
    assert attrs[tracing.STATUS] == "ok"
    assert attrs[tracing.OUTPUT] == "hi"
    assert attrs[tracing.LATENCY_MS] == 7


def test_none_attributes_are_not_written(spans: InMemorySpanExporter) -> None:
    with tracing.run_span(**{tracing.RUN_ID: "none-1", tracing.PARENT_ID: None}):
        pass
    tracing.flush()

    finished = spans.get_finished_spans()
    assert finished
    assert tracing.PARENT_ID not in dict(finished[0].attributes or {})


def test_no_store_means_no_exporter() -> None:
    assert tracing.build_exporter(Settings()) is None


def test_a_store_means_an_otlp_exporter() -> None:
    exporter = tracing.build_exporter(
        Settings(phoenix_url="http://phoenix:6006/", phoenix_api_key="secret")
    )

    assert isinstance(exporter, OTLPSpanExporter)
    assert exporter._endpoint == "http://phoenix:6006/v1/traces"
    assert exporter._client._headers["authorization"] == "Bearer secret"


def test_the_exporter_has_no_auth_header_without_a_key() -> None:
    exporter = tracing.build_exporter(Settings(phoenix_url="http://phoenix:6006"))

    assert isinstance(exporter, OTLPSpanExporter)
    assert "authorization" not in (exporter._client._headers or {})


def test_a_tracer_exists_before_configure(monkeypatch) -> None:
    monkeypatch.setattr(tracing, "_provider", None)

    assert tracing.tracer() is not None


def test_a_provider_without_a_store_exports_nothing() -> None:
    provider = tracing.build_provider(Settings())

    assert isinstance(provider, TracerProvider)


def test_a_provider_with_a_store_has_a_processor() -> None:
    provider = tracing.build_provider(Settings(phoenix_url="http://phoenix:6006"))

    assert isinstance(provider, TracerProvider)
