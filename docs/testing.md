# Testing: host vs Docker

**Rule: host by default; Docker when the boundary is the thing under test.**

Most tests exercise application code. That code is the same whether it runs from `uv run` or from
an image, so rebuilding a container for it adds time and buys no new signal. Docker earns its place
only where the container is part of the failure: the image, compose, environment injection, volumes,
ports, users and service networking.

| Kind | Where | Command |
| --- | --- | --- |
| Unit, HTTP contract, registry, CLI | Host, in-process | `make check`, `make test-all` |
| Integration with a dependency | Host process + containerized dependency | `make test-integration` |
| Packaging / compose | Docker | `make docker-smoke` |
| Live model smoke | Manual, against a running API | `make smoke` |

## The decision test

> Would this test still be meaningful if the app were started directly from source with `uv run`?
> If yes, it belongs on the host. Does it fail only when the image, compose file, environment
> injection, volume, port or network is wrong? Then it belongs in Docker.

A `TestClient` test is an integration-ish test, but it is in-process. It stays on the host.

## What runs where

### Host (`make check`, `make test-all`)

- pytest with `TestModel`: registry, API contract, dependency injection, CLI.
- ruff and basedpyright.
- Coverage with a 95% floor (`make test-all`; currently 100%).
- Fast enough to run on every edit. No model, no network, no database. Integration tests are
  deselected by default (`addopts = "-m 'not integration'"`).

### Integration (`make test-integration`)

- Starts the compose Postgres with `docker compose up -d --wait db`.
- Creates `agplat_test` if it does not exist; migrations run against it.
- Runs `pytest -m integration` on the host with `AGPLAT_TEST_DB_URL` pointing at that database.
- The test process stays on the host; only Postgres is in Docker. The database is left running; `make down` stops it.
- If `AGPLAT_TEST_DB_URL` is missing, the test fails with a clear message, not a skip.

### Docker (`make docker-smoke`)

- Validate `compose.yaml` with `docker compose config`.
- Build the image from `Dockerfile` and the lockfile.
- Run it with **no bind mounts**, so the image must contain `src/`, `agents/` and the code its `CMD`
  names.
- Start with `DEEPSEEK_API_KEY=dummy`: startup only checks that the key exists; `/health` and
  `/agents` never call the model.
- Assert `/health` is `{"status":"ok"}` and `/agents` contains `assistant`, then remove the
  container. The presence check matters: an image with no `agents/` would still return `200` and
  `[]`.

This catches a missing `COPY`, a broken `CMD`, a compose file that no longer parses, and a
file-ownership problem. It does not pretend to be a full compose integration test; the separate
integration lane covers Postgres.

### Not in CI

`make smoke` sends a real prompt and costs tokens. It is a manual check against a running API, not a
regression gate.

## CI

- Every PR: host lint, typecheck, tests and coverage.
- Every PR: host integration tests against a `postgres:17` service.
- Every PR: build the image and run the no-bind-mount smoke.
- Keep pytest itself on the host; only the database is containerized for integration tests.

Do not run the whole pytest suite inside the container. It repeats the host job slowly, and it would
still miss the packaging boundary if the container were built with bind mounts.
