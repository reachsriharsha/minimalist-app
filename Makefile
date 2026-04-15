# Makefile -- developer-ergonomic forwarders into the compose stack.
#
# Every target simply `cd`s into infra/ and invokes `docker compose` so the
# compose file can live in infra/ without forcing every command to type
# `-f infra/docker-compose.yml`.
#
# Targets:
#   make            -- prints this help (default)
#   make up         -- build + start the dev stack in the background
#   make down       -- stop and remove containers (volumes preserved)
#   make logs       -- tail logs for all services
#   make ps         -- show service status
#   make build      -- rebuild images without starting services
#   make migrate    -- run alembic migrations one-shot
#   make clean      -- DESTRUCTIVE: stop stack + delete named volumes
#   make backend-shell   -- open a shell in the running backend container
#   make frontend-shell  -- open a shell in the running frontend container
#   make db-shell        -- open psql against the postgres container

.DEFAULT_GOAL := help

COMPOSE_DIR := infra
COMPOSE := docker compose

.PHONY: help up down logs ps build migrate clean backend-shell frontend-shell db-shell

help:
	@echo "minimalist-app -- docker-compose shortcuts"
	@echo ""
	@echo "  make up              build + start the dev stack (detached)"
	@echo "  make down            stop and remove containers (volumes kept)"
	@echo "  make logs            tail logs for all services"
	@echo "  make ps              show service status"
	@echo "  make build           rebuild images without starting services"
	@echo "  make migrate         run 'alembic upgrade head' one-shot"
	@echo "  make clean           DESTRUCTIVE: stop stack and delete named volumes"
	@echo "  make backend-shell   shell into running backend container"
	@echo "  make frontend-shell  shell into running frontend container"
	@echo "  make db-shell        psql into the postgres container"
	@echo ""
	@echo "Prod profile:"
	@echo "  cd infra && docker compose --profile prod up -d --build"
	@echo ""
	@echo "First-run setup:"
	@echo "  cp infra/.env.example infra/.env && make up"

up:
	cd $(COMPOSE_DIR) && $(COMPOSE) up -d --build

down:
	cd $(COMPOSE_DIR) && $(COMPOSE) down

logs:
	cd $(COMPOSE_DIR) && $(COMPOSE) logs -f

ps:
	cd $(COMPOSE_DIR) && $(COMPOSE) ps

build:
	cd $(COMPOSE_DIR) && $(COMPOSE) build

migrate:
	cd $(COMPOSE_DIR) && $(COMPOSE) run --rm backend migrate

clean:
	@echo ">>> make clean will REMOVE named volumes (pgdata, redisdata, frontend_node_modules, backend_venv)."
	@echo ">>> All database contents and any cached node_modules will be lost."
	cd $(COMPOSE_DIR) && $(COMPOSE) down -v

backend-shell:
	cd $(COMPOSE_DIR) && $(COMPOSE) exec backend /bin/bash

frontend-shell:
	cd $(COMPOSE_DIR) && $(COMPOSE) exec frontend /bin/bash

db-shell:
	cd $(COMPOSE_DIR) && $(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-app}
