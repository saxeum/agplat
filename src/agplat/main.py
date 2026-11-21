"""Composition root: settings in, routes out. Nothing else lives here."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from agplat import api
from agplat.agents.registry import AgentRegistry
from agplat.api.errors import ApiError, api_error_handler
from agplat.runs import RunRepository, RunStore
from agplat.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    registry: AgentRegistry | None = None,
    runs: RunStore | None = None,
) -> FastAPI:
    """Build an app.

    Tests inject a registry built with ``TestModel`` so they need no model and
    no network. Production loads the manifests from disk once, at startup.
    """
    settings = settings or get_settings()

    # Provider keys live in ~/.env, outside the repo. Existing process
    # environment variables win, so containers can inject them directly.
    load_dotenv(Path.home() / ".env")

    registry = registry or AgentRegistry.load(settings.agents_dir)
    runs = runs or RunRepository(settings.db_url)

    app = FastAPI(title="agplat", version="0.0.0")
    app.add_exception_handler(ApiError, api_error_handler)
    app.state.settings = settings
    app.state.registry = registry
    app.state.runs = runs
    app.include_router(api.health.router)
    app.include_router(api.agents.router)
    app.include_router(api.runs.router)
    return app


# Deliberately no module-level app: importing this module must not build models
# or read agents. Uvicorn uses `--factory` (see Makefile and compose.yaml), and
# tests import create_app() directly.
