# Stage 0 — one agent behind four endpoints

Status: **implemented** · 2026-11-21 · commit `d62fccb` · Pydantic AI `2.71.0`

**TL;DR:** FastAPI loads native Pydantic AI `AgentSpec` YAML once at startup, builds one agent, and
exposes discovery plus one run endpoint. No database, tools, streaming, auth or retrieval yet.

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/health` | liveness; no model, no database |
| GET | `/agents` | specs loaded at startup |
| GET | `/agents/{name}` | one agent, with its SHA-256 digest |
| POST | `/agents/{name}/runs` | `{"input": "..."}` → `{run_id, output, usage}` |

The run endpoint needs a model. `agents/assistant.yaml` names `deepseek:deepseek-flash`; tests inject a
`TestModel` registry and never touch it.

## Files

```
agents/assistant.yaml            native AgentSpec
src/agplat/main.py               create_app(): composition root
src/agplat/settings.py           AGPLAT_* environment
src/agplat/deps.py               RunDeps: per-run identity
src/agplat/api/                  routes and the public JSON contract
src/agplat/agents/registry.py    load specs once; digest each file
tests/                           HTTP and registry tests, TestModel only
```

`src/` is 318 lines including docstrings; `tests/` is 156.

## Decisions

- **Native spec, trusted YAML.** `Agent.from_file()` is
  `Agent.from_spec(AgentSpec.from_file(path), ...)`. There is no custom manifest schema. A spec has
  the same authority as the code that builds the agent, so the trust boundary is the repository: a
  manifest commit is reviewed like a Python commit. Unknown keys are ignored; a manifest can name
  native capabilities, including MCP endpoints. Re-restrict when manifests come from outside the
  repo.
- **Framework split.** Pydantic AI owns model calls, tool dispatch, retries, usage accounting and
  `RunContext`; agplat owns spec loading, run identity, limits, storage and the HTTP contract.
- **One construction site.** `AgentRegistry.load()` calls `Agent.from_spec()`, sets
  `deps_type=RunDeps`, and requires a `model` in every spec.
- **Startup validates.** Invalid YAML/spec fields, a missing `model`, a model or capability that
  cannot be built, duplicate names, and an empty agents directory all fail before serving.
- **Dependencies carry identity, not secrets.** `RunDeps(run_id, agent, depth)` is frozen and never
  shown to the model. The platform creates `run_id`; delegation will create `depth + 1`.
- **Model is a spec field.** `agents/assistant.yaml` names `deepseek:deepseek-flash`; a spec without `model`
  fails startup. Provider credentials stay in Pydantic AI's own environment variables.
- **Tests replace the model.** `create_app(settings=..., registry=...)` injects a `TestModel`
  registry; the HTTP layer, spec loading, agent construction and usage accounting all run.
- **Every run is bounded.** `UsageLimits(request_limit=4, tool_calls_limit=AGPLAT_MAX_TOOL_CALLS)`
  (12 by default); usage is returned in the response.
- **REST now, SSE later.** Streaming will be `POST /agents/{name}/runs/stream`, not a
  `"stream": true` flag.

## Not here yet

Postgres and `runs` rows, streaming, tools and retrieval, citations, evals, delegation, graphs, MCP,
auth/queue/UI/cloud. `DESIGN.md` §16 has the order; §17 has the triggers.

## Known gaps

1. `RunDeps.depth` has no cap; nothing creates a child run yet.
2. `run_id` is returned but not stored.
3. `request_limit=4` is a constant, not an `AGPLAT_*` setting.

## Checking the claims

From the repository root:

```
make test
```

`14 passed` (Python 3.12, `TestModel`, no network).

```
make lint
```

`All checks passed!`

```
make typecheck
```

`0 errors, 0 warnings, 0 notes` (basedpyright, `standard` mode, matching Zed's default).

```
find src -name '*.py' -print0 | xargs -0 cat | wc -l
```

`318`

Key references: [Agent Specs](https://pydantic.dev/docs/ai/core-concepts/agent-spec/),
[Agents](https://pydantic.dev/docs/ai/core-concepts/agent/), [Testing](https://pydantic.dev/docs/ai/guides/testing/),
[Usage limits](https://pydantic.dev/docs/ai/core-concepts/agent/#usage-limits),
[Multi-agent Applications](https://pydantic.dev/docs/ai/guides/multi-agent-applications/),
[MCP](https://pydantic.dev/docs/ai/mcp/server/). Checked 2026-11-21.

Testing policy: [testing.md](testing.md) — host for code, Docker for the boundary.
