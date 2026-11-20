"""YAML -> AgentManifest -> Pydantic AI Agent.

Compilation is the only place that constructs an ``Agent``. Keeping it in one
function is what makes the manifest the platform's contract: if a field cannot
be expressed here, it cannot reach a model.
"""

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import Model

from agplat.agents.manifest import AgentManifest
from agplat.deps import RunDeps


class ManifestError(ValueError):
    """A manifest is unreadable, invalid, or names something that does not exist."""


def load_manifest(path: Path) -> AgentManifest:
    """Read one file and validate it, with the filename as part of the contract."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: expected a YAML mapping")

    try:
        manifest = AgentManifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestError(f"{path}: {exc}") from exc

    if manifest.name != path.stem:
        raise ManifestError(f"{path}: name {manifest.name!r} must match the filename {path.stem!r}")
    return manifest


def manifest_digest(path: Path) -> str:
    """Pin behaviour to bytes, so a run can name the config that produced it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def compile_agent(
    manifest: AgentManifest,
    *,
    default_model: str | Model,
    tools: Mapping[str, Callable[..., Any]] | None = None,
) -> Agent[RunDeps, str]:
    """Turn data into an agent. Unknown tool names fail here, at startup."""
    available = tools or {}
    unknown = sorted(set(manifest.tools) - set(available))
    if unknown:
        raise ManifestError(f"{manifest.name}: unknown tools {unknown}; known: {sorted(available)}")

    return Agent(
        manifest.model or default_model,
        name=manifest.name,
        instructions=manifest.instructions,
        deps_type=RunDeps,
        tools=[available[name] for name in manifest.tools],
    )
