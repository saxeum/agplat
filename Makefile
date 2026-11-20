.DEFAULT_GOAL := help

INTEGRATION_DB_URL ?= postgresql://agplat:agplat@127.0.0.1:5432/agplat_test

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the API in Docker (127.0.0.1:8000)
	docker compose up --build -d

down: ## Stop the container
	docker compose down

logs: ## Follow API logs
	docker compose logs -f api

api: ## Run the API on the host with reload (faster than rebuilding)
	uv run uvicorn agplat.main:create_app --factory --reload --host 127.0.0.1 --port 8000

db-migrate: ## Apply SQL migrations to AGPLAT_DB_URL
	uv run python -m agplat.migrate

test: ## Unit and HTTP tests: no model, no network, no database
	uv run pytest -q

test-all: ## Run all tests with coverage (fails under the configured floor)
	uv run pytest --cov=agplat --cov-report=term-missing

test-integration: ## Run DB integration tests against compose Postgres
	docker compose up -d --wait db
	@docker compose exec -T db psql -U agplat -d agplat -tAc "select 1 from pg_database where datname='agplat_test'" | grep -q 1 || docker compose exec -T db createdb -U agplat agplat_test
	AGPLAT_DB_URL=$(INTEGRATION_DB_URL) uv run python -m agplat.migrate
	AGPLAT_TEST_DB_URL=$(INTEGRATION_DB_URL) uv run pytest -m integration -q

docker-smoke: ## Build the image and smoke-test it without bind mounts
	./scripts/docker-smoke.sh

lint: ## Lint
	uv run ruff check src tests

typecheck: ## Type check (basedpyright, Zed's standard mode)
	uv run basedpyright

fmt: ## Format and sort imports (matches Zed's format-on-save)
	uv run ruff check --select I --fix src tests
	uv run ruff format src tests

check: lint typecheck test-all ## Host checks: lint, types, tests, coverage

smoke: ## Hit a running API: health, agents, one live run
	@curl -fsS http://127.0.0.1:8000/health && echo
	@curl -fsS http://127.0.0.1:8000/agents && echo
	@curl -fsS -X POST http://127.0.0.1:8000/agents/assistant/runs \
		-H 'content-type: application/json' \
		-d '{"input": "Reply with the single word: ready"}' && echo
