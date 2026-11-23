PYTHON ?= python
NPM ?= npm

RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy
PYTEST := $(PYTHON) -m pytest

.DEFAULT_GOAL := help

.PHONY: help install dev test test-web lint typecheck client client-check check build migrate sync

help:
	@echo "VN Portfolio Optimizer - development commands"
	@echo ""
	@echo "  make install      Install Python packages (editable) and web dependencies"
	@echo "  make dev          Run the API and the web app together"
	@echo "  make test         Run the Python test suite"
	@echo "  make test-web     Run the web unit tests (Node test runner)"
	@echo "  make lint         Run ruff and the web linter"
	@echo "  make typecheck    Run mypy and the web type checker"
	@echo "  make client       Regenerate the OpenAPI schema and typed web client"
	@echo "  make client-check Fail when the typed client is out of date"
	@echo "  make check        Run lint, typecheck, client check and tests (the full gate)"
	@echo "  make build        Build the web app for production"
	@echo "  make migrate      Apply database migrations (alembic upgrade head)"
	@echo "  make sync         Sync sample tickers + benchmarks (needs providers)"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e packages/core -e packages/data -e "apps/api[dev]"
	$(NPM) --prefix apps/web install

dev:
	$(PYTHON) scripts/dev.py

test:
	$(PYTEST)

test-web:
	$(NPM) --prefix apps/web run test

lint:
	$(RUFF) check asgi.py packages apps/api scripts
	$(NPM) --prefix apps/web run lint

typecheck:
	$(MYPY)
	$(NPM) --prefix apps/web run typecheck

client:
	$(PYTHON) scripts/client.py generate

client-check:
	$(PYTHON) scripts/client.py check

check: lint typecheck client-check test test-web

build:
	$(NPM) --prefix apps/web run build

migrate:
	cd packages/data && $(PYTHON) -m alembic upgrade head

sync:
	$(PYTHON) -m data.jobs.sync --backfill VNM --backfill FPT --backfill ACB --benchmarks
