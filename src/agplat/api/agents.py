"""The agent surface: discover what exists, run one, stream one.

Routes do HTTP only. They never build a prompt or know which model is in use;
the registry owns agent construction, and the tracer owns the run record.
"""

import json
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from pydantic_ai import (
    AgentRunResult,
    AgentRunResultEvent,
    PartDeltaEvent,
    RunUsage,
    TextPartDelta,
    UsageLimits,
)

from agplat import tracing
from agplat.agents.registry import AgentRegistry, LoadedAgent
from agplat.api.errors import ApiError
from agplat.api.schemas import AgentInfo, RunRequest, RunResponse, Usage
from agplat.deps import RunDeps
from agplat.settings import Settings

router = APIRouter(prefix="/agents", tags=["agents"])


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _info(loaded: LoadedAgent, name: str) -> AgentInfo:
    spec = loaded.spec
    assert spec.model is not None  # AgentRegistry.load() rejects a spec without one
    return AgentInfo(
        name=name,
        description=str(spec.description or ""),
        model=spec.model,
        digest=loaded.digest,
    )


def _usage(usage: RunUsage) -> Usage:
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        requests=usage.requests,
        cost=str(usage.cost) if usage.cost is not None else None,
    )


def _limits(settings: Settings) -> UsageLimits:
    """Both ceilings come from settings, so a test or a deployment can tighten them."""
    return UsageLimits(
        request_limit=settings.request_limit,
        tool_calls_limit=settings.max_tool_calls,
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _run_attributes(run_id: str, name: str, digest: str, prompt: str) -> dict[str, Any]:
    return {
        tracing.RUN_ID: run_id,
        tracing.AGENT: name,
        tracing.DIGEST: digest,
        tracing.INPUT: prompt,
    }


def _usage_attributes(usage: RunUsage) -> dict[str, Any]:
    return {
        tracing.INPUT_TOKENS: usage.input_tokens,
        tracing.OUTPUT_TOKENS: usage.output_tokens,
        tracing.REQUESTS: usage.requests,
        tracing.COST: str(usage.cost) if usage.cost is not None else None,
    }


@router.get("", response_model=list[AgentInfo])
def list_agents(request: Request) -> list[AgentInfo]:
    """Every agent this process loaded, in filename order."""
    return [_info(loaded, name) for name, loaded in _registry(request).agents.items()]


@router.get("/{name}", response_model=AgentInfo)
def get_agent(name: str, request: Request) -> AgentInfo:
    try:
        loaded = _registry(request).get(name)
    except KeyError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "unknown_agent",
            f"unknown agent: {name}",
        ) from None
    return _info(loaded, name)


@router.post("/{name}/runs", response_model=RunResponse)
async def run_agent(name: str, body: RunRequest, request: Request) -> RunResponse:
    """Run one turn and wait for it. The run is a span, not a row."""
    try:
        loaded = _registry(request).get(name)
    except KeyError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "unknown_agent",
            f"unknown agent: {name}",
        ) from None

    # The platform owns the run id, not the model. Every tool call and child run
    # inherits it, which is what makes a multi-agent trace readable.
    run_id = uuid4().hex
    started = time.perf_counter()
    failure: str | None = None
    result: AgentRunResult[str] | None = None

    with tracing.run_span(**_run_attributes(run_id, name, loaded.digest, body.input)) as span:
        try:
            result = await loaded.agent.run(
                body.input,
                deps=RunDeps(run_id=run_id, agent=name),
                usage_limits=_limits(_settings(request)),
            )
        except Exception as exc:
            failure = str(exc) or type(exc).__name__
            tracing.finish_span(
                span,
                latency_ms=_elapsed_ms(started),
                **{tracing.STATUS: "failed", tracing.ERROR: failure},
            )
        else:
            tracing.finish_span(
                span,
                latency_ms=_elapsed_ms(started),
                **{
                    tracing.STATUS: "ok",
                    tracing.OUTPUT: result.output,
                    **_usage_attributes(result.usage),
                },
            )

    if failure is not None or result is None:
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "run_failed",
            failure or "run produced no result",
            run_id=run_id,
        )
    return RunResponse(run_id=run_id, output=result.output, usage=_usage(result.usage))


async def _stream_run(
    *,
    loaded: LoadedAgent,
    name: str,
    prompt: str,
    run_id: str,
    limits: UsageLimits,
) -> AsyncGenerator[str, None]:
    yield _sse("run.started", {"run_id": run_id, "agent": name})
    started = time.perf_counter()
    finished = False
    with tracing.run_span(**_run_attributes(run_id, name, loaded.digest, prompt)) as span:
        try:
            result: AgentRunResult[str] | None = None
            async with loaded.agent.run_stream_events(
                prompt,
                deps=RunDeps(run_id=run_id, agent=name),
                usage_limits=limits,
            ) as events:
                async for event in events:
                    if isinstance(event, AgentRunResultEvent):
                        result = event.result
                    elif isinstance(event, PartDeltaEvent) and isinstance(
                        event.delta, TextPartDelta
                    ):
                        delta = event.delta.content_delta
                        if delta:
                            yield _sse("output.delta", {"delta": delta})

            if result is None:
                raise RuntimeError("run finished without a result")

            tracing.finish_span(
                span,
                latency_ms=_elapsed_ms(started),
                **{
                    tracing.STATUS: "ok",
                    tracing.OUTPUT: result.output,
                    **_usage_attributes(result.usage),
                },
            )
            # End and export before telling the client the run finished, so a
            # caller that reads it straight after the last event finds it.
            span.end()
            tracing.flush()
            finished = True
            yield _sse(
                "run.completed",
                {
                    "run_id": run_id,
                    "output": result.output,
                    "usage": _usage(result.usage).model_dump(),
                },
            )
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            tracing.finish_span(
                span,
                latency_ms=_elapsed_ms(started),
                **{tracing.STATUS: "failed", tracing.ERROR: error},
            )
            span.end()
            tracing.flush()
            finished = True
            yield _sse("run.failed", {"run_id": run_id, "code": "run_failed", "detail": error})
        finally:
            if not finished:
                # The consumer went away before the run completed. The span is
                # all the record there is, so say what happened on it.
                tracing.finish_span(
                    span,
                    latency_ms=_elapsed_ms(started),
                    **{tracing.STATUS: "failed", tracing.ERROR: "client disconnected"},
                )


@router.post("/{name}/runs/stream")
async def stream_agent(name: str, body: RunRequest, request: Request) -> StreamingResponse:
    """Run one turn and stream the events as SSE."""
    try:
        loaded = _registry(request).get(name)
    except KeyError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "unknown_agent",
            f"unknown agent: {name}",
        ) from None

    run_id = uuid4().hex
    return StreamingResponse(
        _stream_run(
            loaded=loaded,
            name=name,
            prompt=body.input,
            run_id=run_id,
            limits=_limits(_settings(request)),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
