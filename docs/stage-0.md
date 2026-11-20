# Stage 0 — one agent behind four endpoints

Status: **implemented** · 2026-11-21 · commit `1185d0b` · Pydantic AI `2.71.0`

`DESIGN.md` calls this **Step 0**; stage and step are the same sequence here. This page records what
Stage 0 contains and links the Pydantic AI documentation that justifies each shape. It is evidence
about the architecture, not a second design document: `DESIGN.md` is still the design.

## What this stage is

A FastAPI process that reads YAML manifests once at startup, compiles each one into a Pydantic AI
`Agent`, and exposes discovery plus one run endpoint.

Nothing else: no database, no tools, no streaming, no auth, no knowledge retrieval.

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/health` | liveness; no model, no database |
| GET | `/agents` | manifests loaded at startup |
| GET | `/agents/{name}` | one manifest, with its SHA-256 digest |
| POST | `/agents/{name}/runs` | `{"input": "..."}` → `{run_id, output, usage}` |

The run endpoint needs a model. The default is `ollama:qwen3`; tests never touch it because they
inject a `TestModel` registry.

## The shape, in files

`src/` is 457 lines including docstrings; `tests/` is 122. The interesting part is not the size, it
is that each file has exactly one job.

```
agents/assistant.yaml     the agent: data, not code
src/agplat/main.py        create_app(): composition root, nothing else
src/agplat/settings.py    AGPLAT_* environment
src/agplat/deps.py        RunDeps: what a tool may know about the current run
src/agplat/api/           routes and the public JSON contract
src/agplat/agents/
  manifest.py             the YAML schema (pydantic)
  loader.py               YAML -> AgentManifest -> Pydantic AI Agent
  registry.py             load once; validate delegates; digest each file
tests/                    HTTP and manifest tests, TestModel only
```

## Decisions

### 1. Pydantic AI owns the request path; agplat owns the layer around it

The platform does not re-implement the agent loop. It configures one and wraps it in an HTTP
contract, a manifest schema, and a policy layer.

Pydantic AI describes an `Agent` as a container for instructions, function tools and toolsets,
structured output, the dependency type, and the model
([Agents](https://pydantic.dev/docs/ai/core-concepts/agent/)). The v2 write-up makes the same split
from the other side: the inner loop — call the model, run a tool, feed the result back — is settled,
and the work with leverage is the layer around it
([Pydantic AI v2](https://pydantic.dev/articles/pydantic-ai-v2)).

What agplat owns: manifest validation, tool resolution, run identity, usage policy, storage, and the
HTTP contract. What Pydantic AI owns: model calls, tool dispatch, retries, usage accounting, and
`RunContext`. The dependency is pinned to `pydantic-ai-slim[openai]>=2.71,<3` and locked in
`uv.lock`; CI runs `uv lock --check` so the two cannot drift apart.

### 2. The manifest is data — deliberately not an `AgentSpec`

Pydantic AI already supports declarative agents: `Agent.from_file()` and `AgentSpec` load YAML with
`model`, `instructions`, `capabilities`, `model_settings` and more
([Agent Specs](https://pydantic.dev/docs/ai/core-concepts/agent-spec/)). **Stage 0 does not use
them**, and the documentation says why:

> A spec has the same authority as the code that builds the agent. It chooses the model and provider,
> the instructions, and every capability with its arguments, including the endpoints the agent
> connects to. […] Load specs only from sources you trust.

A manifest under `agents/` is written by whoever can commit to this repo, so that warning is not
hypothetical. Our schema is the restricted subset:

```python
name: str          # ^[a-z][a-z0-9_-]{0,31}$, must equal the filename stem
description: str
instructions: str  # non-empty
model: str | None  # provider:model, or null -> AGPLAT_MODEL
tools: tuple[str, ...]      # names the platform registered
delegates: tuple[str, ...]  # names of other manifests
```

No capabilities, no MCP URLs, no `model_settings`, no code. `extra="forbid"` means an unknown key
fails startup instead of being ignored
([Pydantic config](https://docs.pydantic.dev/latest/api/config/)). Adding a capability or an MCP
server is therefore a platform change with a review, not a YAML edit.

### 3. One construction site

`compile_agent()` in `src/agplat/agents/loader.py` is the only function that calls `Agent(...)`.
Everything a manifest may influence has to pass through it.

`compile_agent()` takes a mapping of tool name to function; the registry passes it through and will
own it once tools arrive. A function tool's JSON schema is derived from its signature and docstring
([Function Tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/)), so a manifest cannot describe
a new tool — it can only name a key in that mapping. Unknown names fail at startup with the list of
known names. The same registry will hold toolsets when MCP arrives
([Toolsets](https://pydantic.dev/docs/ai/tools-toolsets/toolsets/)).

### 4. Startup is the validation boundary

A broken agent graph that only fails at request time is a production incident wearing a config typo.
The registry therefore refuses, at load time:

| Failure | Where it is caught |
| --- | --- |
| YAML is not a mapping, or is invalid YAML | `load_manifest()` |
| `name` does not equal the filename stem | `load_manifest()` |
| unknown key in the YAML | `AgentManifest` (`extra="forbid"`) |
| a tool name the platform has not registered | `compile_agent()` |
| a delegate that does not exist | `AgentRegistry.load()` |
| a delegate cycle (`a -> b -> a`) | `AgentRegistry.load()` |

Delegates are checked even though nothing uses them yet. Delegation is "an agent calls another agent
from inside a tool and takes control back when it finishes"
([Multi-agent Applications](https://pydantic.dev/docs/ai/guides/multi-agent-applications/)); a name
that only resolves on the first user request is exactly the failure this check removes.

Graph-based workflows are deferred. They are the right tool for a fixed, branching process, not for
"ask the right specialist" ([Graphs](https://pydantic.dev/docs/ai/graph/graph/)).

### 5. Dependencies carry run identity, never secrets

`RunDeps` is a frozen dataclass with `run_id`, `agent`, and `depth`. It is passed as `deps=` on every
run and declared as `deps_type=RunDeps` on the agent, so tools will receive it as
`RunContext[RunDeps]` — type-checked, and never shown to the model
([Dependencies](https://pydantic.dev/docs/ai/core-concepts/dependencies/)).

Frozen is the point: a tool cannot rewrite the identity of the run it is serving. Delegation will
create a new `RunDeps` at `depth + 1`, which is what keeps a run tree traceable. `depth` is unused at
Stage 0; it is the hook for the depth cap in Stage 7.

The platform creates `run_id`, not the model. Every future tool call and child run inherits it, so a
multi-agent trace can be reconstructed without guessing.

### 6. The model is a string from the environment

`AGPLAT_MODEL` defaults to `ollama:qwen3`; a manifest may override it with any
`provider:model` string ([Models and Providers](https://pydantic.dev/docs/ai/models/overview/)).
Provider credentials are read by Pydantic AI from its own environment variables; the platform never
stores or logs them.

The default is Ollama, so the PoC needs no API key
([Ollama](https://pydantic.dev/docs/ai/api/models/ollama/)). Ollama's model class requires
`OLLAMA_BASE_URL` at construction time, which is why `create_app()` sets a localhost default
*before* the registry loads. Compose overrides it with `host.docker.internal` so the container can
reach an Ollama on the host.

### 7. Tests replace the model, not the application

`create_app(settings=..., registry=...)` takes both, and `tests/conftest.py` builds a registry with
`TestModel`. The HTTP layer, manifest validation, compilation and usage accounting all execute; no
model, no network, no database ([Unit testing](https://pydantic.dev/docs/ai/guides/testing/),
[`pydantic_ai.models.test`](https://pydantic.dev/docs/ai/api/models/test/)).

This is also why `main.py` has no module-level `app`. Importing the module must not build agents or
read manifests, so uvicorn is started with `--factory` and tests import `create_app` directly. A
module-level app would make the test suite construct the real model as an import side effect.

### 8. Every run is bounded and metered

The run endpoint passes `UsageLimits(request_limit=4, tool_calls_limit=AGPLAT_MAX_TOOL_CALLS)` —
12 by default — and returns the resulting `usage` in the response
([Usage limits](https://pydantic.dev/docs/ai/core-concepts/agent/#usage-limits)). The limit is
per run, so a model that loops on a tool stops with an error instead of a bill. `cost` is serialised
as a string because JSON has no `Decimal` ([`pydantic_ai.usage`](https://pydantic.dev/docs/ai/api/pydantic-ai/usage/)).

`run_id` and usage are returned now and will be written to a `runs` row in Stage 1. A queryable row
per run — with `parent_id` when delegation lands — is the trace. Logs alone cannot answer "which
config produced this answer, and what did it call"; spans carry parent and child relationships that
log lines do not ([Logs vs traces](https://pydantic.dev/articles/why-traces-when-you-have-logs)).

### 9. REST now, streaming later as a separate endpoint

`POST /agents/{name}/runs` waits for the whole turn and returns one JSON body. Streaming will be
`POST /agents/{name}/runs/stream` returning SSE, not a `"stream": true` flag: the response content
type differs, and two endpoints with one shape each are easier to read and test. The framework
primitive is already documented
([Streaming events and final output](https://pydantic.dev/docs/ai/core-concepts/agent/#streaming-events-and-final-output)).

## What is deliberately absent

Each row is deferred until the step that needs it; the right-hand column is the documentation that
step will read first.

| Absent | Arrives at | Pydantic AI documentation |
| --- | --- | --- |
| Postgres, migrations, `runs` rows | Step 1 | — (the run row is agplat's own contract) |
| SSE streaming | Step 1 | [Streaming](https://pydantic.dev/docs/ai/core-concepts/agent/#streaming-events-and-final-output) |
| Tools and the tool registry | Steps 2–5 | [Function Tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/) |
| Embeddings and retrieval | Steps 3–4 | [Embeddings](https://pydantic.dev/docs/ai/guides/embeddings/) |
| Citations in the response | Step 5 | [Citations](https://pydantic.dev/docs/ai/core-concepts/citations/) |
| Evals as a CI gate | Step 5 | [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) |
| The `delegate` tool and depth cap | Step 7 | [Multi-agent Applications](https://pydantic.dev/docs/ai/guides/multi-agent-applications/) |
| Graph workflows | only if a fixed branch is needed | [Graphs](https://pydantic.dev/docs/ai/graph/graph/) |
| MCP server and client | Step 8 | [Server](https://pydantic.dev/docs/ai/mcp/server/), [Client](https://pydantic.dev/docs/ai/mcp/client/) |
| Auth, queue, UI, cloud | §17 of `DESIGN.md`, each with a trigger | — |

## Known gaps at Stage 0

These are real and currently true. None blocks Stage 0's exit test; each is named so it is a
decision rather than a surprise.

1. **The bare Docker image cannot start.** `Dockerfile` ends with
   `CMD ["uvicorn", "agplat.main:app", ...]`, but there is intentionally no module-level `app`.
   Compose overrides the command with `agplat.main:create_app --factory`, so the compose path is
   unaffected; `docker run` of the image is not. The image also does not `COPY agents/` — compose
   mounts it.
2. **README claims the code is "under 200 lines"; `src/` is 457.** The claim predates the docstrings
   and is now false.
3. **`RunDeps.depth` has no cap.** `AGPLAT_MAX_DEPTH` appears in `DESIGN.md` but not in `Settings`,
   and nothing creates a child run yet.
4. **`delegates` is validated but unused.** No tool reads it until Stage 7.
5. **`run_id` is returned but not stored.** A restart loses it; Stage 1 adds the row.
6. **`request_limit=4` is a constant**, not an `AGPLAT_*` setting. It was the smallest honest number
   for a single-turn endpoint.

## Checking the claims

Run from the repository root. Expected result is printed below each block.

```
make test
```

`11 passed` in well under a second (Python 3.12, `TestModel`, no network). The wall time varies run
to run; the count and the absence of network calls are the claim.

```
make lint
```

`All checks passed!`

Source line count quoted above:

```
find src -name '*.py' -print0 | xargs -0 cat | wc -l
```

`457`

Every external link on this page, checked 2026-11-21. Each line should print `200`:

```
for u in \
  https://pydantic.dev/docs/ai/core-concepts/agent/ \
  https://pydantic.dev/docs/ai/core-concepts/agent-spec/ \
  https://pydantic.dev/docs/ai/core-concepts/dependencies/ \
  https://pydantic.dev/docs/ai/core-concepts/citations/ \
  https://pydantic.dev/docs/ai/tools-toolsets/tools/ \
  https://pydantic.dev/docs/ai/tools-toolsets/toolsets/ \
  https://pydantic.dev/docs/ai/models/overview/ \
  https://pydantic.dev/docs/ai/api/models/ollama/ \
  https://pydantic.dev/docs/ai/api/models/test/ \
  https://pydantic.dev/docs/ai/api/pydantic-ai/usage/ \
  https://pydantic.dev/docs/ai/guides/testing/ \
  https://pydantic.dev/docs/ai/guides/multi-agent-applications/ \
  https://pydantic.dev/docs/ai/guides/embeddings/ \
  https://pydantic.dev/docs/ai/evals/evals/ \
  https://pydantic.dev/docs/ai/mcp/server/ \
  https://pydantic.dev/docs/ai/mcp/client/ \
  https://pydantic.dev/docs/ai/graph/graph/ \
  https://docs.pydantic.dev/latest/api/config/ \
  https://pydantic.dev/articles/pydantic-ai-v2 \
  https://pydantic.dev/articles/why-traces-when-you-have-logs ; do
  curl -s -o /dev/null -w "%{http_code} $u\n" -L "$u"
done
```
