# =============================================================================
# SignaPlan - Makefile unificado
# =============================================================================
# Uso:
#   make dev          → Levanta entorno de desarrollo
#   make prod-deploy  → Despliega en producción
#   make logs         → Ver logs en tiempo real
#   make help         → Ver todos los comandos disponibles
# =============================================================================

.PHONY: help dev dev-build dev-down dev-restart prod-deploy prod-down prod-logs \
        migrate migrate-new backup restore test test-unit test-integration \
        logs shell db-shell clean init-saas

# Detectar compose file según entorno
DEV_COMPOSE  = docker-compose.yml
PROD_COMPOSE = docker-compose.prod.yml

# ─────────────────────────────────────────────────────────────────────────────
# AYUDA
# ─────────────────────────────────────────────────────────────────────────────
help: ## Muestra esta ayuda
	@echo ""
	@echo "╔════════════════════════════════════════╗"
	@echo "║     SignaPlan - Comandos Make          ║"
	@echo "╚════════════════════════════════════════╝"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# DESARROLLO
# ─────────────────────────────────────────────────────────────────────────────
dev: ## Levanta entorno de desarrollo
	docker compose -f $(DEV_COMPOSE) up -d --build
	@echo ""
	@echo "✓ Entorno de desarrollo listo"
	@echo "  http://localhost       (esquema public)"
	@echo "  http://demo.localhost  (tenant demo)"
	@echo ""

dev-build: ## Rebuild completo (sin caché) + levantar
	docker compose -f $(DEV_COMPOSE) build --no-cache
	docker compose -f $(DEV_COMPOSE) up -d

dev-down: ## Detener entorno de desarrollo
	docker compose -f $(DEV_COMPOSE) down

dev-restart: ## Reiniciar solo el contenedor web (rápido)
	docker compose -f $(DEV_COMPOSE) restart web

# ─────────────────────────────────────────────────────────────────────────────
# PRODUCCIÓN
# ─────────────────────────────────────────────────────────────────────────────
prod-deploy: ## Desplegar en producción (build + up)
	@bash scripts/deploy.sh --build --migrate

prod-update: ## Actualizar producción (git pull + rebuild)
	@bash scripts/deploy.sh --build

prod-down: ## Detener producción
	docker compose -f $(PROD_COMPOSE) down

prod-logs: ## Logs de producción en tiempo real
	docker compose -f $(PROD_COMPOSE) logs -f

prod-status: ## Estado de los servicios en producción
	docker compose -f $(PROD_COMPOSE) ps

# ─────────────────────────────────────────────────────────────────────────────
# MIGRACIONES
# ─────────────────────────────────────────────────────────────────────────────
migrate: ## Aplicar migraciones pendientes (dev)
	docker compose -f $(DEV_COMPOSE) exec web flask db upgrade

migrate-new: ## Crear nueva migración. Uso: make migrate-new MSG="descripcion"
	docker compose -f $(DEV_COMPOSE) exec web flask db migrate -m "$(MSG)"

migrate-prod: ## Aplicar migraciones en producción
	docker compose -f $(PROD_COMPOSE) exec -T web flask db upgrade

# ─────────────────────────────────────────────────────────────────────────────
# BACKUPS
# ─────────────────────────────────────────────────────────────────────────────
backup: ## Crear backup (DB + uploads) - usa COMPOSE_FILE de prod por defecto
	@COMPOSE_FILE=$(PROD_COMPOSE) bash scripts/backup.sh

backup-dev: ## Backup del entorno de desarrollo
	@COMPOSE_FILE=$(DEV_COMPOSE) bash scripts/backup.sh

restore: ## Restaurar backup. Uso: make restore TS=20260607_120000
	@COMPOSE_FILE=$(PROD_COMPOSE) bash scripts/restore.sh $(TS)

# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────
test: ## Ejecutar todos los tests (dev - usa DB de test)
	docker compose -f $(DEV_COMPOSE) exec web bash -c "pip install -q -r requirements-test.txt 2>/dev/null && pytest tests/ -v --tb=short"

test-unit: ## Solo tests unitarios (dev)
	docker compose -f $(DEV_COMPOSE) exec web bash -c "pip install -q -r requirements-test.txt 2>/dev/null && pytest tests/unit/ -v"

test-integration: ## Solo tests de integración (dev)
	docker compose -f $(DEV_COMPOSE) exec web bash -c "pip install -q -r requirements-test.txt 2>/dev/null && pytest tests/integration/ -v"

smoke: ## Smoke tests post-deploy (seguro en prod). Uso: make smoke DOMAIN=signaplan.com
	@bash scripts/smoke-test.sh $(DOMAIN)

smoke-prod: ## Smoke tests en producción (signaplan.com)
	@COMPOSE_FILE=$(PROD_COMPOSE) bash scripts/smoke-test.sh signaplan.com

smoke-dev: ## Smoke tests en desarrollo (localhost)
	@COMPOSE_FILE=$(DEV_COMPOSE) bash scripts/smoke-test.sh localhost

# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────
logs: ## Ver logs del entorno de desarrollo
	docker compose -f $(DEV_COMPOSE) logs -f

logs-web: ## Logs solo del servicio web
	docker compose -f $(DEV_COMPOSE) logs -f web

shell: ## Abrir shell en el contenedor web (dev)
	docker compose -f $(DEV_COMPOSE) exec web bash

db-shell: ## Abrir psql en la base de datos (dev)
	docker compose -f $(DEV_COMPOSE) exec db psql -U postgres gestion_obra_saas

init-saas: ## Inicializar SaaS (crear tenant demo)
	docker compose -f $(DEV_COMPOSE) exec web python init_saas.py

clean: ## Limpiar todo (contenedores, volúmenes, imágenes huérfanas)
	docker compose -f $(DEV_COMPOSE) down -v --remove-orphans
	docker image prune -f
	@echo "✓ Limpieza completada (volúmenes eliminados - DATA LOST)"
