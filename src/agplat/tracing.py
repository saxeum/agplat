"""Run records are OpenTelemetry spans, and Phoenix stores them.

There is no local database. A run span carries the fields the API returns as
``agplat.*`` attributes, so ``GET /runs/{id}`` reads the same record back from
the trace store. The honest consequence: a span that was never exported does
not exist, and a process that dies mid-run leaves no row behind.

Tracing stays optional. With ``AGPLAT_PHOENIX_URL`` unset the app runs with a
provider that has no exporter, so everything works and nothing is stored.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span

from agplat.settings import Settings

logger = logging.getLogger(__name__)

# Attribute names are the storage schema now, so they are spelled once.
AGENT = "agplat.agent"
RUN_ID = "agplat.run_id"
DIGEST = "agplat.manifest_digest"
INPUT = "agplat.input"
STATUS = "agplat.status"
OUTPUT = "agplat.output"
ERROR = "agplat.error"
INPUT_TOKENS = "agplat.input_tokens"
OUTPUT_TOKENS = "agplat.output_tokens"
REQUESTS = "agplat.requests"
COST = "agplat.cost"
LATENCY_MS = "agplat.latency_ms"
PARENT_ID = "agplat.parent_id"

_provider: TracerProvider | None = None


def build_exporter(settings: Settings) -> SpanExporter | None:
    """An OTLP exporter when a store is configured, and nothing otherwise."""
    if not settings.phoenix_url:
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    headers = (
        {"Authorization": f"Bearer {settings.phoenix_api_key}"}
        if settings.phoenix_api_key
        else None
    )
    return OTLPSpanExporter(
        endpoint=f"{settings.phoenix_url.rstrip('/')}/v1/traces",
        headers=headers,
    )


def build_provider(settings: Settings, exporter: SpanExporter | None = None) -> TracerProvider:
    """A provider with an exporter attached only when there is somewhere to send."""
    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    exporter = exporter if exporter is not None else build_exporter(settings)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def configure(settings: Settings, exporter: SpanExporter | None = None) -> None:
    """Install the tracer provider once per process.

    ``exporter`` exists so tests can capture spans in memory; production
    passes nothing and gets OTLP when ``AGPLAT_PHOENIX_URL`` is set.
    """
    global _provider
    if _provider is not None:
        return

    provider = build_provider(settings, exporter)
    trace.set_tracer_provider(provider)
    _provider = provider

    # Model, tool and run spans exist only if Pydantic AI is instrumented; this
    # is the one line that turns its tracing on.
    from pydantic_ai import Agent

    Agent.instrument_all()


def flush(timeout_ms: int = 500) -> bool:
    """Push finished spans out, so a run is readable immediately after it ends."""
    if _provider is None:
        return True
    return _provider.force_flush(timeout_millis=timeout_ms)


def tracer() -> trace.Tracer:
    """The tracer this module emits through.

    Bound to the provider built here rather than looked up globally: a library
    that installed a provider first would otherwise silently take the spans.
    """
    if _provider is not None:
        return _provider.get_tracer("agplat")
    return trace.get_tracer("agplat")


@contextmanager
def run_span(**attributes: Any) -> Iterator[Span]:
    """The root span for one run; everything else nests under it.

    Flushing on the way out is part of the contract: the span is the record, so
    it is on its way to the store before the caller sees the run end. This also
    runs when a streaming consumer disconnects, which is when the record matters
    most.
    """
    try:
        with tracer().start_as_current_span("run") as span:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
            span.set_attribute(STATUS, "running")
            yield span
    finally:
        flush()


def finish_span(span: Span, *, latency_ms: int, **attributes: Any) -> None:
    """Record the terminal state on the run span."""
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)
    span.set_attribute(LATENCY_MS, latency_ms)
