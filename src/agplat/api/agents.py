"""The agent surface: discover what exists, run one.

Routes do HTTP only. They never build a prompt, open a connection or know which
model is in use; the registry and the built agent own all of that.
"""

import logging
import time
from uuid import uuid4

from fastapi import APIRouter, Request, status
from pydantic_ai import UsageLimits

from agplat.agents.registry import AgentRegistry, LoadedAgent
from agplat.api.errors import ApiError
from agplat.api.schemas import AgentInfo, RunRequest, RunResponse, Usage
from agplat.deps import RunDeps
from agplat.runs import RunStore
from agplat.settings import Settings

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _runs(request: Request) -> RunStore:
    return request.app.state.runs


def _info(loaded: LoadedAgent, name: str) -> AgentInfo:
    spec = loaded.spec
    assert spec.model is not None  # AgentRegistry.load() rejects a spec without one
    return AgentInfo(
        name=name,
        description=str(spec.description or ""),
        model=spec.model,
        digest=loaded.digest,
    )


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
    """Run one turn and wait for it. Streaming is Step 1."""
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
    runs = _runs(request)
    await runs.create_running(
        run_id,
        agent=name,
        manifest_digest=loaded.digest,
        input=body.input,
    )

    started = time.perf_counter()
    try:
        result = await loaded.agent.run(
            body.input,
            deps=RunDeps(run_id=run_id, agent=name),
            usage_limits=UsageLimits(
                request_limit=4,
                tool_calls_limit=_settings(request).max_tool_calls,
            ),
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = str(exc) or type(exc).__name__
        try:
            await runs.finish_failed(run_id, error=error, latency_ms=latency_ms)
        except Exception:
            logger.exception("could not record failed run %s", run_id)
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "run_failed",
            error,
            run_id=run_id,
        ) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = result.usage
    await runs.finish_ok(
        run_id,
        output=result.output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        requests=usage.requests,
        cost=usage.cost,
        latency_ms=latency_ms,
    )
    return RunResponse(
        run_id=run_id,
        output=result.output,
        usage=Usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            requests=usage.requests,
            cost=str(usage.cost) if usage.cost is not None else None,
        ),
    )
