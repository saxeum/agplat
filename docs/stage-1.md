# Stage 1 — durable runs, streaming, and a database

Status: **implemented** · 2026-11-21 · commit `79d6659` · Pydantic AI `2.71.0` · Postgres `17`

> Amended after the fact: this is the record of `79d6659`, when a run was a row in Postgres and the
> suite had a database lane. Runs are now spans in Phoenix, there is no database, and
> `DESIGN.md` §14 states what that costs. The decisions below are otherwise as shipped.

**TL;DR:** every run is a row written before the model is called and updated when it ends, over
either a waiting endpoint or an SSE one. `GET /runs/{id}` reads the row and its usage back. Both
ceilings a run has come from `AGPLAT_*` settings. Postgres arrives here, not in Step 2, because a run
record is a database row.

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/health` | liveness; no model, no database |
| GET | `/agents` | specs loaded at startup |
| GET | `/agents/{name}` | one agent, with its SHA-256 digest |
| POST | `/agents/{name}/runs` | `{"input": "..."}` → `{run_id, output, usage}`, after the model finishes |
| POST | `/agents/{name}/runs/stream` | the same turn as SSE: `run.started`, `output.delta`, `run.completed` \| `run.failed` |
| GET | `/runs/{id}` | the stored row, its usage, and its children; never calls a model |

Startup needs `DEEPSEEK_API_KEY` to exist in the environment or `~/.env`, because the manifest names a
DeepSeek model and a spec whose model cannot be built fails before `/health` answers. The discovery
and read endpoints never call the model; only the two run endpoints do.

## Files

```
migrations/0001_runs.sql         runs, three indexes, and the status check
src/agplat/db.py                 connect and apply forward-only migrations
src/agplat/migrate.py            python -m agplat.migrate (make db-migrate)
src/agplat/runs.py               Run, RunStore protocol, RunRepository: all the SQL
src/agplat/api/runs.py           GET /runs/{id}
src/agplat/api/agents.py         run and stream endpoints, SSE event contract
src/agplat/api/schemas.py        RunInfo and Usage: the read-side JSON contract
tests/test_integration.py        the four tests that need a real Postgres
tests/fakes.py                   FakeRunStore, so the host suite needs no database
```

`src/` is 850 lines including docstrings; `tests/` is 1,131. The three files worth rereading are
`runs.py`, the streaming half of `api/agents.py`, and `db.py`'s migration loop.

## Decisions

- **The row is written first.** `create_running()` inserts `status='running'` before the model is
  called, then `finish_ok()` or `finish_failed()` updates the same row. A process that dies mid-run
  leaves a `running` row rather than no record, which is the difference between "we lost a call" and
  "nothing happened". Latency is measured around the model call and stored in milliseconds.
- **The platform owns the identifier.** `run_id` is a UUID minted by the route before the model sees
  the prompt; `RunDeps(run_id, agent, depth)` carries it to every tool call and future child run.
  `POST` returns it, `GET /runs/{id}` finds it, and nothing reconstructs it from a log line.
- **One limit builder, two endpoints.** `_limits(settings)` builds the `UsageLimits` and both
  endpoints take it, so `AGPLAT_REQUEST_LIMIT` and `AGPLAT_MAX_TOOL_CALLS` cannot apply to one path
  and not the other. Both are per-run ceilings, not daily budgets (DESIGN.md §7).
- **Streaming is a second endpoint, not a flag.** `POST /agents/{name}/runs/stream` returns
  `text/event-stream`; the event names are the contract. Deltas are only text (`TextPartDelta`), and
  the terminal event carries either the same `usage` the waiting endpoint returns or the error.
- **A dropped client ends the run, and says so.** The generator's `finally` block records
  `failed: client disconnected` if the consumer went away before completion, so a cancelled stream is
  never left as a permanently `running` row. It is not resumable: the run is lost, and that is a known
  gap below.
- **Routes never see SQL.** They take a `RunStore`; the repository is the only thing that opens a
  connection. Tests inject `FakeRunStore`, so the host suite stays fast and database-free, and the
  four integration tests are the only thing that proves the SQL.
- **Migrations are committed SQL, applied explicitly.** `python -m agplat.migrate` applies each
  unapplied `*.sql` file in filename order, in one transaction per file, recording the filename in
  `schema_migrations`. No Alembic: the runner is 42 lines and the schema is one table. Running
  migrations at startup was rejected — it makes a deploy able to change a shared database.
- **`cost` is `Decimal` in the database and a string in JSON**, because JSON has no decimal type and
  a float would round-trip `0.0000147` into something else.
- **`GET /runs/{id}` is a read.** It never builds an agent, calls a model or takes a limit. An unknown
  id is `404 run_not_found`; a known one returns the row, `usage` (only for `ok` rows), and children.

## Not here yet

Tools, retrieval, citations, evals, delegation, MCP, auth. `DESIGN.md` §16 has the order; §17 has the
triggers. Step 2 is the read-only `sql_query` role.

## Known gaps

1. **Nothing creates a child run.** `parent_id` is in the schema, `RunRepository.list_children()` and
   the response's `children` field both work, and `RunDeps.depth` is still uncapped — but no route
   sets a parent until the `delegate` tool arrives in Step 7.
2. **`make up` does not migrate.** The image carries `migrations/`, but applying them is a separate
   command, so a fresh clone must run `make db-migrate` once before its first `POST .../runs`.
   Moving that into compose is Step 9's "clean checkout runs the demo end to end".
3. **One connection per query.** `RunRepository` opens and closes an `asyncpg` connection per call.
   Correct at one caller and readable; a pool is a mechanism for a concurrency that does not exist
   yet.
4. **SSE cannot resume.** A dropped connection marks the run `failed`; there is no replay or
   re-attach. Streaming is for a cooperative client on loopback.

## Checking the claims

From the repository root, at `79d6659`:

```
make check
```

`39 passed, 4 deselected`, and `Total coverage: 100.00%` (350 statements, 30 branches, 95% floor).

```
make test-integration
```

`4 passed, 39 deselected` — migrations, repository round-trip, and both routes against the compose
Postgres.

```
make docker-smoke
```

`health: {"status":"ok"}` and `agents: [{"name":"assistant", …}]`, from an image with no bind mounts.

These need a model key in `~/.env` and spend tokens, so they are not CI:

```
make up
make db-migrate
curl -s -N -X POST http://127.0.0.1:8000/agents/assistant/runs/stream \
  -H 'content-type: application/json' \
  -d '{"input": "Count from 1 to 10, one number per line"}'
```

`event: run.started`, then 18 × `event: output.delta`, then `event: run.completed` with a `run_id`.

```
curl -s http://127.0.0.1:8000/runs/<run_id> | python3 -m json.tool
```

The stored row, for example: `status: "ok"`, the output, `usage.requests: 1`,
`usage.cost: "0.00003945"`, `latency_ms: 692`, `children: []`. Cost and latency differ per run; the
shape does not.

Key references: [Agents streaming](https://pydantic.dev/docs/ai/core-concepts/agent/#streaming),
[Usage limits](https://pydantic.dev/docs/ai/core-concepts/agent/#usage-limits),
[asyncpg](https://magicstack.github.io/asyncpg/current/), [Server-Sent
Events](https://html.spec.whatwg.org/multipage/server-sent-events.html). Checked 2026-11-21.

Testing policy: [testing.md](testing.md) — host for code, Docker for the boundary.
Stage 0: [stage-0.md](stage-0.md).
