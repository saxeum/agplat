"""Process settings.

Every value is an environment variable with the ``AGPLAT_`` prefix; the defaults
are what ``docker compose up`` gives you. Nothing here is a secret: provider
keys are read by Pydantic AI from its own environment variables, never stored
by the platform. ``phoenix_api_key`` is optional and only needed when the trace
store has auth turned on.
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

    # Where the *.yaml agent manifests live, relative to the working directory.
    agents_dir: Path = Path("agents")

    # Run records are spans. Unset means nothing is stored and GET /runs/{id}
    # answers 503; the runs themselves still work.
    phoenix_url: str | None = None
    phoenix_project: str = "default"
    phoenix_api_key: str | None = None
    service_name: str = "agplat"

    # Per-run ceilings, so a model that loops stops instead of spending. These
    # are run limits, not a daily budget; see DESIGN.md §7 and §12.
    request_limit: int = 4
    max_tool_calls: int = 12


@lru_cache
def get_settings() -> Settings:
    """Load once per process. Tests clear the cache if they change the env."""
    return Settings()
