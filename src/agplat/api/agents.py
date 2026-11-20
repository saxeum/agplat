"""The agent surface: discover what exists, run one.

Routes do HTTP only. They never build a prompt, open a connection or know which
model is in use; the registry and the built agent own all of that.
"""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic_ai import UsageLimits

from agplat.agents.registry import AgentRegistry, LoadedAgent
from agplat.api.schemas import AgentInfo, RunRequest, RunResponse, Usage
from agplat.deps import RunDeps
from agplat.settings import Settings

router = APIRouter(prefix="/agents", tags=["agents"])


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _info(loaded: LoadedAgent, name: str, default_model: str) -> AgentInfo:
    spec = loaded.spec
    return AgentInfo(
        name=name,
        description=spec.description or "",
        model=spec.model or default_model,
        digest=loaded.digest,
    )


@router.get("", response_model=list[AgentInfo])
def list_agents(request: Request) -> list[AgentInfo]:
    """Every agent this process loaded, in filename order."""
    registry = _registry(request)
    default_model = _settings(request).model
    return [_info(loaded, name, default_model) for name, loaded in registry.agents.items()]


@router.get("/{name}", response_model=AgentInfo)
def get_agent(name: str, request: Request) -> AgentInfo:
    try:
        loaded = _registry(request).get(name)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown agent: {name}") from None
    return _info(loaded, name, _settings(request).model)


@router.post("/{name}/runs", response_model=RunResponse)
async def run_agent(name: str, body: RunRequest, request: Request) -> RunResponse:
    """Run one turn and wait for it. Streaming is Step 1."""
    try:
        loaded = _registry(request).get(name)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown agent: {name}") from None

    # The platform owns the run id, not the model. Every tool call and child run
    # inherits it, which is what makes a multi-agent trace readable.
    run_id = uuid4().hex
    result = await loaded.agent.run(
        body.input,
        deps=RunDeps(run_id=run_id, agent=name),
        usage_limits=UsageLimits(
            request_limit=4,
            tool_calls_limit=_settings(request).max_tool_calls,
        ),
    )

    usage = result.usage
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
