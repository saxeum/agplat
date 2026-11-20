"""Shared fixtures: a registry built with TestModel, so tests need no model."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from agplat.agents.registry import AgentRegistry
from agplat.main import create_app

AGENTS_DIR = Path(__file__).parent.parent / "agents"


@pytest.fixture
def client() -> Iterator[TestClient]:
    registry = AgentRegistry.load(AGENTS_DIR, default_model=TestModel())
    with TestClient(create_app(registry=registry)) as test_client:
        yield test_client
