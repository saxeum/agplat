"""A manifest is validated at startup; these are the failures worth naming."""

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from agplat.agents.loader import ManifestError, compile_agent, load_manifest
from agplat.agents.manifest import AgentManifest
from agplat.agents.registry import AgentRegistry


def write(directory: Path, name: str, body: str) -> Path:
    path = directory / f"{name}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_name_must_match_the_filename(tmp_path: Path) -> None:
    path = write(tmp_path, "a", "name: b\ninstructions: hi\n")

    with pytest.raises(ManifestError, match="must match the filename"):
        load_manifest(path)


def test_unknown_yaml_keys_are_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "a",
        "name: a\ninstructions: hi\ncapabilities: [WebSearch]\n",
    )

    with pytest.raises(ManifestError):
        load_manifest(path)


def test_unknown_tool_is_rejected() -> None:
    manifest = AgentManifest(name="a", instructions="hi", tools=("nope",))

    with pytest.raises(ManifestError, match="unknown tools"):
        compile_agent(manifest, default_model=TestModel())


def test_unknown_delegate_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "a", "name: a\ninstructions: hi\ndelegates: [b]\n")

    with pytest.raises(ManifestError, match="unknown delegate"):
        AgentRegistry.load(tmp_path, default_model=TestModel())


def test_delegate_cycle_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "a", "name: a\ninstructions: hi\ndelegates: [b]\n")
    write(tmp_path, "b", "name: b\ninstructions: hi\ndelegates: [a]\n")

    with pytest.raises(ManifestError, match="delegate cycle"):
        AgentRegistry.load(tmp_path, default_model=TestModel())
