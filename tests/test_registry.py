"""Native AgentSpecs are loaded once; these are the failures worth naming."""

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from agplat.agents.registry import AgentRegistry


def write(directory: Path, name: str, body: str) -> Path:
    path = directory / f"{name}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_a_native_spec(tmp_path: Path) -> None:
    write(tmp_path, "a", "name: a\ninstructions: hi\n")

    loaded = AgentRegistry.load(tmp_path, default_model=TestModel()).get("a")

    assert loaded.agent.name == "a"
    assert loaded.digest


def test_name_falls_back_to_the_filename(tmp_path: Path) -> None:
    write(tmp_path, "a", "instructions: hi\n")

    loaded = AgentRegistry.load(tmp_path, default_model=TestModel()).get("a")

    assert loaded.agent.name == "a"


def test_invalid_spec_fails_startup(tmp_path: Path) -> None:
    write(tmp_path, "a", "instructions: 42\n")

    with pytest.raises(ValueError, match="a.yaml"):
        AgentRegistry.load(tmp_path, default_model=TestModel())


def test_duplicate_names_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, "a", "name: same\ninstructions: hi\n")
    write(tmp_path, "b", "name: same\ninstructions: hi\n")

    with pytest.raises(ValueError, match="duplicate agent name"):
        AgentRegistry.load(tmp_path, default_model=TestModel())
