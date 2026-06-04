.PHONY: install dev dev-api dev-worker migrate revision test lint fmt seed-compliance

install:
	cd api && uv sync

dev:
	$(MAKE) -j2 dev-api dev-worker

dev-api:
	cd api && uv run uvicorn app.main:app --reload --port 8000

dev-worker:
	cd api && uv run python -m app.workers.main

migrate:
	cd api && uv run alembic upgrade head

revision:
	cd api && uv run alembic revision -m "$(m)"

test:
	cd api && uv run pytest

lint:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app

fmt:
	cd api && uv run ruff check --fix . && uv run ruff format .

seed-compliance:
	cd api && uv run python -m app.compliance.seed_loader
