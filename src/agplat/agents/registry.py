"""Load native Pydantic AI AgentSpecs once; the registry is read-only afterwards."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.agent.spec import AgentSpec
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model

from agplat.deps import RunDeps


@dataclass(frozen=True)
class LoadedAgent:
    """One spec, the agent built from it, and the bytes it came from."""

    spec: AgentSpec
    agent: Agent[RunDeps, str]
    digest: str


@dataclass(frozen=True)
class AgentRegistry:
    """Every agent this process will serve. Immutable by construction."""

    agents: dict[str, LoadedAgent]

    @classmethod
    def load(cls, directory: Path, *, model: Model | None = None) -> "AgentRegistry":
        """Build every agent. ``model`` is a test override; production uses the spec's model."""
        paths = sorted(directory.glob("*.yaml"))
        if not paths:
            raise ValueError(f"{directory}: no *.yaml manifests found")

        agents: dict[str, LoadedAgent] = {}
        for path in paths:
            try:
                spec = AgentSpec.from_file(path)
                name = spec.name or path.stem
                if not spec.model:
                    raise ValueError(f"{path}: model is required")
                if name in agents:
                    raise ValueError(f"{path}: duplicate agent name {name!r}")
                agent = Agent.from_spec(
                    spec,
                    deps_type=RunDeps,
                    model=model,
                    name=name,
                )
            except (yaml.YAMLError, ValidationError, UserError) as exc:
                raise ValueError(f"{path}: {exc}") from exc

            agents[name] = LoadedAgent(
                spec=spec,
                agent=agent,
                digest=hashlib.sha256(path.read_bytes()).hexdigest()[:12],
            )
        return cls(agents=agents)

    def get(self, name: str) -> LoadedAgent:
        try:
            return self.agents[name]
        except KeyError:
            raise KeyError(f"unknown agent: {name}") from None
