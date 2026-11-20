"""Liveness only: no database, no model, no agent. Compose uses this."""

from fastapi import APIRouter

router = APIRouter(tags=["ops"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
