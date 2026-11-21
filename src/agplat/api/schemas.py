"""Request and response shapes. This is the public JSON contract."""

from datetime import datetime

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """One user turn. Capped so a caller cannot post a megabyte prompt."""

    input: str = Field(min_length=1, max_length=32_000)


class Usage(BaseModel):
    """What the run cost. ``cost`` is a string because JSON has no Decimal."""

    input_tokens: int
    output_tokens: int
    requests: int
    cost: str | None = None


class RunResponse(BaseModel):
    run_id: str
    output: str
    usage: Usage


class RunInfo(BaseModel):
    """A persisted run, with its children."""

    run_id: str
    parent_id: str | None
    agent: str
    manifest_digest: str
    input: str
    output: str | None
    status: str
    error: str | None
    usage: Usage | None = None
    latency_ms: int | None
    created_at: datetime
    children: list["RunInfo"] = Field(default_factory=list)


class AgentInfo(BaseModel):
    """What a caller can discover about an agent without reading its YAML."""

    name: str
    description: str
    model: str
    digest: str
