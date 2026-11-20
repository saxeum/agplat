"""Shared fixtures: a registry built with TestModel, so tests need no model."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from agplat.agents.registry import AgentRegistry
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


@pytest.fixture
def client(runs: FakeRunStore) -> Iterator[TestClient]:
    registry = AgentRegistry.load(AGENTS_DIR, model=TestModel())
    with TestClient(create_app(registry=registry, runs=runs)) as test_client:
        yield test_client
