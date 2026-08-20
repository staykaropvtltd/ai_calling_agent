# ============================================================
# Staykaro AI Caller — Makefile
# Common dev and ops commands.
# ============================================================

COMPOSE      := docker compose --profile all
COMPOSE_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile all

.PHONY: help up down build logs ps restart lint test deploy clean shell-api

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Local development ─────────────────────────────────────────────────────────

up: ## Start all services (detached)
	$(COMPOSE) up -d

down: ## Stop all services and remove containers
	$(COMPOSE) down

build: ## Rebuild all Docker images
	$(COMPOSE) build --parallel

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

ps: ## Show container status and ports
	$(COMPOSE) ps

restart: ## Restart all services
	$(COMPOSE) restart

shell-api: ## Open a shell inside the api container
	docker exec -it staykaro-api /bin/bash

# ── Quality checks ─────────────────────────────────────────────────────────────

lint: ## Run ruff on all Python source
	ruff check app/ services/

lint-fix: ## Auto-fix ruff violations
	ruff check --fix app/ services/

test: ## Run unit tests with coverage
	REDIS_URL=redis://localhost:6379/0 \
	DATABASE_URL=postgresql+psycopg://test:test@localhost:5432/test \
	BLAND_API_KEY=dummy \
	pytest app/tests/ --cov=app --cov-report=term-missing

# ── Production ────────────────────────────────────────────────────────────────

deploy: ## Rebuild + restart (production compose stack)
	$(COMPOSE_PROD) build --parallel
	$(COMPOSE_PROD) up -d --remove-orphans
	$(COMPOSE_PROD) ps

prod-logs: ## Follow production logs
	$(COMPOSE_PROD) logs -f

prod-down: ## Stop production stack
	$(COMPOSE_PROD) down

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean: ## Remove stopped containers and dangling images
	docker compose down --remove-orphans
	docker image prune -f
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
