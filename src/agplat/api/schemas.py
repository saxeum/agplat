"""Request and response shapes. This is the public JSON contract."""

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


class AgentInfo(BaseModel):
    """What a caller can discover about an agent without reading its YAML."""

    name: str
    description: str
    model: str
    digest: str
