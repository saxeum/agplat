"""Read one persisted run. No model call happens here."""

from fastapi import APIRouter, Request, status

from agplat.api.errors import ApiError
from agplat.api.schemas import RunInfo, Usage
from agplat.runs import Run, RunStore

router = APIRouter(prefix="/runs", tags=["runs"])


def _runs(request: Request) -> RunStore:
    return request.app.state.runs


def _info(run: Run, children: list[Run]) -> RunInfo:
    usage = None
    if run.status == "ok":
        usage = Usage(
            input_tokens=run.input_tokens or 0,
            output_tokens=run.output_tokens or 0,
            requests=run.requests or 0,
            cost=str(run.cost) if run.cost is not None else None,
        )
    return RunInfo(
        run_id=run.id,
        parent_id=run.parent_id,
        agent=run.agent,
        manifest_digest=run.manifest_digest,
        input=run.input,
        output=run.output,
        status=run.status,
        error=run.error,
        usage=usage,
        latency_ms=run.latency_ms,
        created_at=run.created_at,
        children=[_info(child, []) for child in children],
    )


@router.get("/{run_id}", response_model=RunInfo)
async def get_run(run_id: str, request: Request) -> RunInfo:
    """Return the row and its direct children. Reading never calls a model."""
    runs = _runs(request)
    run = await runs.get(run_id)
    if run is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "run_not_found",
            f"unknown run: {run_id}",
        )
    children = await runs.list_children(run_id)
    return _info(run, children)
