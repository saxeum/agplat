"""Composition root: settings in, routes out. Nothing else lives here."""

import os

from fastapi import FastAPI

from agplat import api
from agplat.agents.registry import AgentRegistry
from agplat.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    registry: AgentRegistry | None = None,
) -> FastAPI:
    """Build an app.

    Tests inject a registry built with ``TestModel`` so they need no model and
    no network. Production loads the manifests from disk once, at startup.
    """
    settings = settings or get_settings()

    # Pydantic AI reads the Ollama endpoint from OLLAMA_BASE_URL. The platform
    # supplies a local default so `ollama:` model strings work on the host
    # without extra exports; compose overrides it for host.docker.internal.
    os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    registry = registry or AgentRegistry.load(
        settings.agents_dir,
        default_model=settings.model,
    )

    app = FastAPI(title="agplat", version="0.0.0")
    app.state.settings = settings
    app.state.registry = registry
    app.include_router(api.health.router)
    app.include_router(api.agents.router)
    return app


# Deliberately no module-level app: importing this module must not build models
# or read agents. Uvicorn uses `--factory` (see Makefile and compose.yaml), and
# tests import create_app() directly.
