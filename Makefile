.PHONY: help install dev test lint format migrate up down logs shell clean

help:
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install:  ## Install dev dependencies into a local venv.
	python -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/pre-commit install || true

dev:  ## Run the API server with auto-reload.
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:  ## Run the test suite.
	pytest

test-unit:
	pytest tests/unit

test-integration:
	pytest tests/integration

lint:
	ruff check app tests

format:
	ruff format app tests
	ruff check --fix app tests

type-check:
	mypy app

migrate:
	alembic upgrade head

migration:  ## make migration m="describe change"
	alembic revision --autogenerate -m "$(m)"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

shell:
	docker compose exec api /bin/bash

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
