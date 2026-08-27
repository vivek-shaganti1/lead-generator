# =============================================================================
#  Lead Generator — developer tasks
#
#  Backend runs from backend/.venv (Python 3.13, ruff + pytest).
#  Frontend runs from frontend/ (Node 20+, Next.js 15).
#  Everything below assumes you run `make` from the repository root.
# =============================================================================

PYTHON  ?= python3
VENV    := backend/.venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help env whoami install install-backend install-frontend venv dev-backend dev-frontend \
        worker beat test test-cov lint lint-fix typecheck migrate migration \
        up down restart logs build ps shell clean

## ---------------------------------------------------------------- help ------

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## ------------------------------------------------------------- install ------

$(PY):
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

venv: $(PY) ## Create backend/.venv if it does not exist

install: install-backend install-frontend ## Install backend + frontend dependencies

install-backend: venv ## Install Python deps (runtime + dev) into backend/.venv
	$(PIP) install -r backend/requirements-dev.txt

install-frontend: ## Install Node deps with a clean, lockfile-exact install
	cd frontend && npm ci

## ------------------------------------------------------------- develop ------

env: ## Create .env from the example, with a generated SECRET_KEY
	@test -f .env && echo ".env already exists — leaving it alone" && exit 0 || true
	@sed "s|^SECRET_KEY=.*|SECRET_KEY=$$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')|" \
		.env.example > .env
	@echo "wrote .env — set ADMIN_EMAIL and ADMIN_PASSWORD, then run 'make dev-backend'"

whoami: ## Show the login the API will accept, and where it read it from
	@cd backend && .venv/bin/python -c "\
from app.config import settings, _ENV_FILES; \
print('env files :', [str(p) for p in (_ENV_FILES or [])] or '(none - ENV=test)'); \
print('admin     :', settings.admin_email); \
print('database  :', settings.database_url); \
print(); \
print('Changes to .env need an API restart to take effect.')"

dev-backend: ## Run the API with autoreload on http://localhost:8000
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Run the Next.js dashboard on http://localhost:3000
	cd frontend && npm run dev

worker: ## Run a Celery worker (needs Redis)
	cd backend && .venv/bin/celery -A app.workers.celery_app.celery_app worker --loglevel=info

beat: ## Run the Celery beat scheduler (needs Redis)
	cd backend && .venv/bin/celery -A app.workers.celery_app.celery_app beat --loglevel=info

## ---------------------------------------------------------------- test ------

test: ## Run the backend test suite (SQLite, no services required)
	cd backend && .venv/bin/pytest

test-cov: ## Run the tests with a coverage report
	cd backend && .venv/bin/pytest --cov=app --cov-report=term-missing

lint: ## Lint the backend with ruff
	cd backend && .venv/bin/ruff check app tests

lint-fix: ## Lint and apply the safe autofixes
	cd backend && .venv/bin/ruff check --fix app tests

typecheck: ## Type-check the frontend with tsc --noEmit
	cd frontend && npm run typecheck

## ------------------------------------------------------------ database ------

migrate: ## Apply all Alembic migrations to DATABASE_URL
	cd backend && .venv/bin/alembic upgrade head

migration: ## Autogenerate a migration:  make migration m="add foo"
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

## -------------------------------------------------------------- docker ------

up: ## Build and start the whole stack in the background
	$(COMPOSE) up -d --build

down: ## Stop the stack (volumes are kept)
	$(COMPOSE) down

restart: down up ## Stop and start the stack

build: ## Rebuild the container images without starting them
	$(COMPOSE) build

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Tail logs from every service (make logs s=api for one)
	$(COMPOSE) logs -f --tail=100 $(s)

shell: ## Open a Python shell inside the api container
	$(COMPOSE) exec api /app/entrypoint.sh shell

## --------------------------------------------------------------- clean ------

clean: ## Remove build, cache and test artefacts (keeps .venv and node_modules)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	rm -rf backend/.coverage backend/htmlcov backend/coverage.xml
	rm -rf frontend/.next frontend/out frontend/.turbo
	find . -name '.DS_Store' -delete
