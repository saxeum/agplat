"""The YAML an agent author writes.

This schema is deliberately smaller than a Pydantic AI AgentSpec: no provider
strings except an optional model alias, no capability names, no URLs. Anything
that could add network access or execute code is a platform change, not a
manifest change.
"""

from pydantic import BaseModel, ConfigDict, Field

NAME_PATTERN = r"^[a-z][a-z0-9_-]{0,31}$"


class AgentManifest(BaseModel):
    """A validated agent definition, loaded once at startup."""

    # extra="forbid": a typo in a key must fail startup, not be ignored.
    # frozen=True: manifests are read-only once the registry has them.
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=NAME_PATTERN)
    description: str = ""
    instructions: str = Field(min_length=1)
    model: str | None = None
    tools: tuple[str, ...] = ()
    delegates: tuple[str, ...] = ()
