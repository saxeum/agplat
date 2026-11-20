"""Load every manifest once; the registry is read-only for the process lifetime.

The registry is also where cross-manifest rules live: a delegate must exist, and
the delegation graph must be acyclic. Both are startup errors, because a broken
agent graph that only fails at request time is a production incident wearing a
config typo.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from agplat.agents.loader import (
    ManifestError,
    compile_agent,
    load_manifest,
    manifest_digest,
)
from agplat.agents.manifest import AgentManifest
from agplat.deps import RunDeps


@dataclass(frozen=True)
class LoadedAgent:
    """One manifest, the agent compiled from it, and the bytes it came from."""

    manifest: AgentManifest
    agent: Agent[RunDeps, str]
    digest: str


@dataclass(frozen=True)
class AgentRegistry:
    """Every agent this process will serve. Immutable by construction."""

    agents: dict[str, LoadedAgent]

    @classmethod
    def load(
        cls,
        directory: Path,
        *,
        default_model: str | Model,
        tools: Mapping[str, Callable[..., Any]] | None = None,
    ) -> "AgentRegistry":
        paths = sorted(directory.glob("*.yaml"))
        if not paths:
            raise ManifestError(f"{directory}: no *.yaml manifests found")

        manifests = {path.stem: load_manifest(path) for path in paths}
        _check_delegates(manifests)

        return cls(
            agents={
                name: LoadedAgent(
                    manifest=manifest,
                    agent=compile_agent(manifest, default_model=default_model, tools=tools),
                    digest=manifest_digest(directory / f"{name}.yaml"),
                )
                for name, manifest in manifests.items()
            }
        )

    def get(self, name: str) -> LoadedAgent:
        try:
            return self.agents[name]
        except KeyError:
            raise KeyError(f"unknown agent: {name}") from None


def _check_delegates(manifests: dict[str, AgentManifest]) -> None:
    """Every delegate exists, and following delegates cannot loop."""
    for name, manifest in manifests.items():
        for delegate in manifest.delegates:
            if delegate not in manifests:
                raise ManifestError(
                    f"{name}: unknown delegate {delegate!r}; known: {sorted(manifests)}"
                )

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in done:
            return
        if name in visiting:
            cycle = " -> ".join([*path, name])
            raise ManifestError(f"delegate cycle: {cycle}")
        visiting.add(name)
        for delegate in manifests[name].delegates:
            visit(delegate, [*path, name])
        visiting.remove(name)
        done.add(name)

    for name in manifests:
        visit(name, [])
