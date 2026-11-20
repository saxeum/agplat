"""Process settings.

Every value is an environment variable with the ``AGPLAT_`` prefix; the defaults
are what ``docker compose up`` gives you. Nothing here is a secret: provider
keys are read by Pydantic AI from its own environment variables, never stored
by the platform.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The knobs this process reads. Grow this only when a step needs a knob."""

    model_config = SettingsConfigDict(
        env_prefix="AGPLAT_",
        env_file=".env",
        extra="ignore",
    )

    # The model every agent uses unless its manifest names one. A local Ollama
    # model by default, so the PoC works with no API key.
    model: str = "ollama:qwen3"

    # Where the *.yaml agent manifests live, relative to the working directory.
    agents_dir: Path = Path("agents")

    # A per-run ceiling on tool calls, so a model that loops stops instead of
    # spending. This is a run limit, not a daily budget; see DESIGN.md §7.
    max_tool_calls: int = 12


@lru_cache
def get_settings() -> Settings:
    """Load once per process. Tests clear the cache if they change the env."""
    return Settings()
