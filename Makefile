# TutorTrack developer commands. Backend commands run on the host with uv against the
# docker-compose backing services (`make infra`). `make dev` runs the whole stack in Docker.
#
# Windows: install make (`winget install ezwinports.make`) or run the commands below directly.

BE := cd backend &&
FE := cd frontend &&
UV := uv run

.PHONY: help dev infra down logs install test test-be test-fe e2e lint fmt typecheck check \
        migrate makemigrations migrations-check shell seed openapi api-client api-client-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

dev: ## Start the full stack in Docker (backend, worker, beat, frontend, infra)
	docker compose up -d --build
	@echo "Admin app:  http://localhost:5173"
	@echo "API:        http://localhost:8010/api/v1/docs/"
	@echo "Mailpit:    http://localhost:8025"
	@echo "S3 (local): http://localhost:9010"

infra: ## Start only backing services (postgres, redis, s3, mailpit)
	docker compose up -d postgres redis s3 mailpit

down: ## Stop the stack
	docker compose down

logs: ## Tail stack logs
	docker compose logs -f --tail=100

install: ## Install backend and frontend dependencies on the host
	$(BE) uv sync
	$(FE) pnpm install

test: test-be test-fe ## Run all tests

test-be: ## Backend tests (parallel, with coverage)
	$(BE) $(UV) pytest -n auto --cov --cov-report=term-missing:skip-covered

test-fe: ## Frontend unit tests
	$(FE) pnpm -r test

e2e: ## Playwright end-to-end tests (requires `make dev`)
	$(FE) pnpm e2e

lint: ## Lint backend and frontend
	$(BE) $(UV) ruff check .
	$(BE) $(UV) ruff format --check .
	$(FE) pnpm -r lint

fmt: ## Auto-format backend and frontend
	$(BE) $(UV) ruff check --fix .
	$(BE) $(UV) ruff format .
	$(FE) pnpm -r format

typecheck: ## mypy + tsc
	$(BE) $(UV) mypy
	$(FE) pnpm -r typecheck

migrations-check: ## Fail if model changes are missing migrations
	$(BE) $(UV) python manage.py makemigrations --check --dry-run

check: lint typecheck migrations-check test api-client-check ## Everything CI runs. Must pass before a ticket is done.

migrate: ## Apply migrations
	$(BE) $(UV) python manage.py migrate

makemigrations: ## Create migrations
	$(BE) $(UV) python manage.py makemigrations

shell: ## Django shell
	$(BE) $(UV) python manage.py shell

seed: ## Load demo data
	$(BE) $(UV) python manage.py seed_demo

openapi: ## Write the OpenAPI schema to frontend/packages/api-client/openapi.json
	$(BE) $(UV) python manage.py spectacular --file ../frontend/packages/api-client/openapi.json --format openapi-json --validate

api-client: openapi ## Regenerate the TypeScript API client from OpenAPI
	$(FE) pnpm --filter @tutortrack/api-client generate

api-client-check: api-client ## Fail if the committed API client is out of date
	git diff --exit-code -- frontend/packages/api-client/
