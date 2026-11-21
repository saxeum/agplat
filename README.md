# agplat

A local, REST-only, multi-agent knowledge platform. FastAPI in front, Pydantic AI
behind it, Phoenix for run records, Docker around it all.

**Design: [DESIGN.md](DESIGN.md).** Start there; this file is the quickstart.
**Testing policy: [docs/testing.md](docs/testing.md).** Host for code, Docker for the boundary.
**Stage 1: [docs/stage-1.md](docs/stage-1.md).** The record of the commit it names; runs are
spans in Phoenix now, which is what this file and `DESIGN.md` §14 describe.
**Stage 0: [docs/stage-0.md](docs/stage-0.md).** The record of the first commit, kept as it was.

Current status: **Step 1** — one agent, every run a span in Phoenix, over a waiting
endpoint or SSE, with per-run ceilings from `AGPLAT_*` settings. No database, no tools
and no retrieval yet. See [DESIGN.md §16](DESIGN.md#16-build-order) for the order the
rest arrives in.

## Run it

With Docker (the deliverable):

```bash
make up          # build and start api + phoenix, on 127.0.0.1:8000
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/agents
curl -s -X POST http://127.0.0.1:8000/agents/assistant/runs \
  -H 'content-type: application/json' \
  -d '{"input": "hello"}'
curl -s http://127.0.0.1:8000/runs/<run_id> | python3 -m json.tool
```

The first `make up` builds the image and returns before the API is listening; wait
until `/health` answers `{"status":"ok"}` before expecting the rest to serve. Phoenix
takes a few seconds longer than the API on its first start.

Phoenix is the run store: its UI is at <http://127.0.0.1:6006>, and `GET /runs/{id}`
answers from it. With `AGPLAT_PHOENIX_URL` unset the API still runs and answers
`503 tracing_disabled` on that one endpoint, because nothing was stored.

The service needs a model key **at startup**, not just for a run: `agents/assistant.yaml`
names `deepseek:deepseek-flash`, and a spec whose model cannot be built fails the
container before `/health` answers. Put `DEEPSEEK_API_KEY` in `~/.env` (compose and the
host both load it), or edit that `model:` field to any Pydantic AI model string.

To watch a run instead of waiting for it:

```bash
curl -s -N -X POST http://127.0.0.1:8000/agents/assistant/runs/stream \
  -H 'content-type: application/json' \
  -d '{"input": "Count from 1 to 10, one number per line"}'
```

On the host (faster while reading code):

```bash
uv sync
make api        # :8000 with reload
make test       # no model, no network, no trace store
make test-all   # tests + coverage (fails under 95%)
make typecheck  # basedpyright, standard mode
make check      # lint + typecheck + tests + coverage
make docker-smoke  # build the image; health and agents; no model call
```

## Endpoints (Step 1)

| Method | Path | Use |
| --- | --- | --- |
| GET | `/health` | liveness; used by compose |
| GET | `/agents` | manifests loaded at startup |
| GET | `/agents/{name}` | one manifest, with its digest |
| POST | `/agents/{name}/runs` | `{"input": "..."}` → `{run_id, output, usage}` |
| POST | `/agents/{name}/runs/stream` | the same turn as SSE: `run.started`, `output.delta`, `run.completed` \| `run.failed` |
| GET | `/runs/{id}` | one stored run, its usage and its children; no model call |

Interactive docs at <http://127.0.0.1:8000/docs> while it runs.

## Layout

```
agents/assistant.yaml     the agent: data, not code
src/agplat/main.py        composition root
src/agplat/settings.py    AGPLAT_* environment
src/agplat/deps.py        RunDeps: what a tool may know
src/agplat/tracing.py     the tracer, the run span and its attribute names
src/agplat/runs.py        reading runs back out of Phoenix
src/agplat/api/           HTTP routes, the SSE contract, response models
src/agplat/agents/        native AgentSpec loader and registry
tests/                    HTTP and registry tests, TestModel only
```

Read them in that order. `src/` is about 950 lines, docstrings included; the
registry (`agents/registry.py`), the attribute names in `tracing.py` and the event
loop in `api/agents.py`'s `_stream_run` are the parts worth rereading.

## The rule this repo is built around

A manifest is a **native Pydantic AI `AgentSpec`**. It can name a model, instructions,
and built-in capabilities; `Agent.from_spec()` is the only function that builds an
agent. That trusts the YAML, so manifests are reviewed like code: the trust boundary
is the repository, not the file. The platform still owns run identity, usage limits,
and the HTTP contract.

## Not here

No UI, no auth, no cloud, no queue, no version registry. `DESIGN.md` §17 lists
each with the trigger that would justify it, rather than pretending they are
free.
