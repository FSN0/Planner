# =============================================================================
# SignaPlan - Makefile unificado
# =============================================================================
# Uso:
#   make dev          → Levanta entorno de desarrollo
#   make prod-deploy  → Despliega en producción
#   make logs         → Ver logs en tiempo real
#   make help         → Ver todos los comandos disponibles
# =============================================================================

.PHONY: help sync-brand dev dev-build dev-down dev-restart prod-deploy prod-down prod-logs \
        migrate migrate-new backup restore test test-db test-unit test-integration \
        test-ledger test-pwa test-erp test-informe test-pin test-plan test-comercial \
        test-oficina test-onboarding lan-tunnel logs shell db-shell clean init-saas

# Detectar compose file según entorno
DEV_COMPOSE  = docker-compose.yml
PROD_COMPOSE = docker-compose.prod.yml

# Los tests corren contra una base de datos aparte que se borra a cada vuelta.
TEST_DB           = gestion_obra_test
TEST_DATABASE_URL = postgresql://postgres:$${POSTGRES_PASSWORD:-postgres}@db:5432/$(TEST_DB)
PYTEST            = docker compose -f $(DEV_COMPOSE) exec \
                        -e TEST_DATABASE_URL="$(TEST_DATABASE_URL)" \
                        web python -m pytest

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
sync-brand: ## Copia logos desde logos_signaplan/ a static/img/brand
	@bash scripts/sync_brand_assets.sh

dev: ## Levanta entorno de desarrollo
	@$(MAKE) sync-brand
	docker compose -f $(DEV_COMPOSE) up -d --build
	@echo ""
	@echo "✓ Entorno de desarrollo listo"
	@echo "  http://localhost       (esquema public)"
	@echo "  http://demo.localhost  (tenant demo)"
	@echo ""

dev-build: ## Rebuild completo (sin caché) + levantar
	@$(MAKE) sync-brand
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

migrate-prod: ## Aplicar migraciones en producción (funciona aunque web esté parado)
	@bash scripts/fix_migration_heads.sh
	docker compose -f $(PROD_COMPOSE) build web
	docker compose -f $(PROD_COMPOSE) up -d db
	@sleep 3
	docker compose -f $(PROD_COMPOSE) run --rm --no-deps web flask db upgrade

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
test-db: ## Crea la base de datos de test si no existe
	@docker compose -f $(DEV_COMPOSE) exec -T db \
		psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$(TEST_DB)'" \
		| grep -q 1 \
		|| docker compose -f $(DEV_COMPOSE) exec -T db createdb -U postgres $(TEST_DB)

test: test-db ## Ejecutar todos los tests (dev - usa DB de test)
	$(PYTEST) tests/ -v --tb=short

test-unit: test-db ## Solo tests unitarios (dev)
	$(PYTEST) tests/unit/ -v

test-integration: test-db ## Solo tests de integración (dev)
	$(PYTEST) tests/integration/ -v

test-ledger: test-db ## Solo tests del libro de fichajes
	$(PYTEST) tests/integration/test_fichaje_ledger.py -v

test-pwa: test-db ## Solo tests de la app de fichaje del operario
	$(PYTEST) tests/integration/test_pwa_operario.py -v

test-erp: test-db ## Solo tests del volcado del ERP al libro de fichajes
	$(PYTEST) tests/integration/test_fichaje_erp_ledger.py -v

test-informe: test-db ## Solo tests del informe de registro de jornada
	$(PYTEST) tests/integration/test_fichaje_informe.py -v

test-pin: test-db ## Solo tests del acceso DNI + PIN
	$(PYTEST) tests/integration/test_pin_auth.py -v

test-plan: test-db ## Solo tests del freemium / cupo de plantilla
	$(PYTEST) tests/integration/test_plan_limits.py -v

test-comercial: test-db ## Alta, legales, recuperación y exención de cobro
	$(PYTEST) tests/integration/test_signup_legal_password.py -v

test-oficina: test-db ## Obra Oficina opcional
	$(PYTEST) tests/integration/test_oficina_obra.py -v

test-onboarding: test-db ## Wizard post-alta y panel hoy en obra
	$(PYTEST) tests/integration/test_onboarding_hoy.py -v

lan-tunnel: ## Túnel Cloudflare para probar /mi desde el móvil
	bash scripts/lan-tunnel.sh

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
