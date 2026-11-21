"""Shared fixtures: a registry built with TestModel, so tests need no model."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agplat.agents.registry import AgentRegistry
from agplat.deps import RunDeps
from agplat.main import create_app
from tests.fakes import FakeRunStore

AGENTS_DIR = Path(__file__).parent.parent / "agents"


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("AGPLAT_TEST_DB_URL")
    if not url:
        pytest.fail("AGPLAT_TEST_DB_URL is not set; run `make test-integration`")
    return url


@pytest.fixture
def runs() -> FakeRunStore:
    return FakeRunStore()


def tool_calling_agent() -> Agent[RunDeps, str]:
    """An agent whose turn costs two model requests, so ``request_limit=1`` bites."""
    agent: Agent[RunDeps, str] = Agent(
        TestModel(), deps_type=RunDeps, instructions="call the tool"
    )

    @agent.tool_plain
    def ping() -> str:
        return "pong"

    return agent


@pytest.fixture
def client(runs: FakeRunStore) -> Iterator[TestClient]:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    with TestClient(create_app(registry=registry, runs=runs)) as test_client:
        yield test_client
