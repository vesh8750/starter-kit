# Every routine task has a make target. If you find yourself typing a long command
# twice, it belongs here.
.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help install dev run test test-unit test-cov lint format typecheck check \
        migrate migration downgrade db-reset shell clean docker-build docker-up docker-down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install all dependencies
	uv sync
	@if [ -d .git ]; then uv run pre-commit install; \
	else echo "note: not a git repository yet -- run 'git init' then 'make install' to enable hooks"; fi

dev: ## Run the API with autoreload
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

run: ## Run the API the way production does (no reload)
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

test: ## Run the full test suite
	uv run pytest

test-unit: ## Run only the tests that need no database
	uv run pytest tests/unit -m "not integration"

test-cov: ## Run tests with a coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html

lint: ## Lint
	uv run ruff check .

format: ## Format and apply safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Type-check with mypy (strict)
	uv run mypy

check: format lint typecheck test ## Everything CI runs, locally

migrate: ## Apply all pending migrations
	uv run alembic upgrade head

migration: ## Autogenerate a migration:  make migration m="add orders table"
	@test -n "$(m)" || (echo "usage: make migration m=\"describe the change\"" && exit 1)
	uv run alembic revision --autogenerate -m "$(m)"
	@echo "Review the generated file before committing -- autogenerate is a draft, not an answer."

downgrade: ## Roll back the most recent migration
	uv run alembic downgrade -1

db-reset: ## Drop, recreate and migrate the development database (destructive)
	dropdb --if-exists pet_dev && createdb pet_dev
	$(MAKE) migrate

shell: ## Python REPL with the app importable
	uv run python

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

docker-build: ## Build the production image
	docker build -t pet-backend:local .

docker-up: ## Start the full local stack (api + postgres + redis)
	docker compose up --build

docker-down: ## Stop the local stack and remove volumes
	docker compose down -v
