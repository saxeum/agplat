.DEFAULT_GOAL := help

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

test: ## Unit and HTTP tests: no model, no network, no database
	uv run pytest -q

lint: ## Lint
	uv run ruff check src tests

typecheck: ## Type check (basedpyright, Zed's standard mode)
	uv run basedpyright

fmt: ## Format and sort imports (matches Zed's format-on-save)
	uv run ruff check --select I --fix src tests
	uv run ruff format src tests

check: lint typecheck test ## Run everything CI runs

smoke: ## Hit a running API: health, agents, one live run
	@curl -fsS http://127.0.0.1:8000/health && echo
	@curl -fsS http://127.0.0.1:8000/agents && echo
	@curl -fsS -X POST http://127.0.0.1:8000/agents/assistant/runs \
		-H 'content-type: application/json' \
		-d '{"input": "Reply with the single word: ready"}' && echo
