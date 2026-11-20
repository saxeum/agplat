# agplat

A local, REST-only, multi-agent knowledge platform. FastAPI in front, Pydantic AI
behind it, Postgres with pgvector underneath, Docker around it all.

**Design: [DESIGN.md](DESIGN.md).** Start there; this file is the quickstart.

Current status: **Step 0** — one agent, two read endpoints, one run endpoint.
No database and no tools yet. See [DESIGN.md §16](DESIGN.md#16-build-order) for
the order the rest arrives in.

## Run it

With Docker (the deliverable):

```bash
docker compose up --build
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/agents
curl -s -X POST http://127.0.0.1:8000/agents/assistant/runs \
  -H 'content-type: application/json' \
  -d '{"input": "hello"}'
```

The last call needs a model. The default is a local Ollama model
(`ollama:qwen3`); run Ollama on the host, or copy `.env.example` to `.env` and
point `AGPLAT_MODEL` at any Pydantic AI model string.

On the host (faster while reading code):

```bash
uv sync
make api        # :8000 with reload
make test       # no model, no network, no database
```

## Endpoints (Step 0)

| Method | Path | Use |
| --- | --- | --- |
| GET | `/health` | liveness; used by compose |
| GET | `/agents` | manifests loaded at startup |
| GET | `/agents/{name}` | one manifest, with its digest |
| POST | `/agents/{name}/runs` | `{"input": "..."}` → `{run_id, output, usage}` |

Interactive docs at <http://127.0.0.1:8000/docs> while it runs.

## Layout

```
agents/assistant.yaml     the agent: data, not code
src/agplat/main.py        composition root
src/agplat/settings.py    AGPLAT_* environment
src/agplat/deps.py        RunDeps: what a tool may know
src/agplat/api/           HTTP routes and response models
src/agplat/agents/        manifest schema, compiler, registry
tests/                    HTTP and manifest tests, TestModel only
```

Read them in that order. The whole of Step 0 is under 200 lines; the compiler
(`agents/loader.py`) is the part worth rereading.

## The rule this repo is built around

A manifest is **data**. It may name tools that the platform registered, and
delegates that exist, and nothing else: no URLs, no code, no provider
credentials. `compile_agent()` is the only function allowed to construct an
agent, so if a field cannot pass through it, it cannot reach a model.

## Not here

No UI, no auth, no cloud, no queue, no version registry. `DESIGN.md` §17 lists
each with the trigger that would justify it, rather than pretending they are
free.
