"""Composition root: settings in, routes out. Nothing else lives here."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from agplat import api, tracing
from agplat.agents.registry import AgentRegistry
from agplat.api.errors import ApiError, api_error_handler
from agplat.runs import PhoenixStore, RunStore
from agplat.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    registry: AgentRegistry | None = None,
    runs: RunStore | None = None,
) -> FastAPI:
    """Build an app.

    Tests inject a registry built with ``TestModel`` so they need no model and
    no network, and a store so they need no trace backend. Production loads the
    manifests from disk once, at startup, and stores runs in Phoenix.
    """
    settings = settings or get_settings()

    # Provider keys live in ~/.env, outside the repo. Existing process
    # environment variables win, so containers can inject them directly.
    load_dotenv(Path.home() / ".env")

    # Installs the tracer once per process. With no store configured there is
    # no exporter, so runs work and nothing is remembered.
    tracing.configure(settings)

    registry = registry or AgentRegistry.load(settings.agents_dir)
    if runs is None and settings.phoenix_url:
        runs = PhoenixStore(
            settings.phoenix_url,
            project=settings.phoenix_project,
            api_key=settings.phoenix_api_key,
        )

    # Request spans are off: health probes are not runs, and compose probes
    # /health every ten seconds, so they would be most of the store.
    app = FastAPI(title="agplat", version="0.0.0", telemetry={"tracing": False})
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
